//! Push/Fold (All-in or Fold) preflop poker solver for 2-4 players.
//!
//! Uses External Sampling MCCFR to find the Nash equilibrium of the
//! push-or-fold game where each player's only options are to shove
//! their entire stack or fold.
//!
//! Usage:
//!   target/release/push_fold --players 3 --stack 10 --iterations 1000000
//!   target/release/push_fold --players 2 --stack 15 --iterations 500000
//!   target/release/push_fold --players 4 --stack 8 --iterations 2000000 --ante 0.125

use clap::Parser;
use dcfr_solver::card::{Card, Hand, NUM_CARDS};
use dcfr_solver::eval::{evaluate, Strength};
use dcfr_solver::iso::{canonical_hand, CanonicalHand};
use rand::rngs::SmallRng;
use rand::{Rng, SeedableRng};
use std::fs::File;
use std::io::BufWriter;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NUM_CANONICAL: usize = 169;
/// Actions: 0 = push, 1 = fold
const NUM_ACTIONS: usize = 2;
const PUSH: usize = 0;
const FOLD: usize = 1;

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

#[derive(Parser)]
#[command(name = "push_fold", about = "Push/Fold preflop solver (2-4 players)")]
struct Args {
    /// Number of players (2-4)
    #[arg(long, default_value_t = 3)]
    players: usize,

    /// Stack size in big blinds (equal stacks)
    #[arg(long, default_value_t = 8)]
    stack: u32,

    /// Ante per player in big blinds (0 for no ante)
    #[arg(long, default_value_t = 0.0)]
    ante: f64,

    /// Number of MCCFR iterations
    #[arg(long, default_value_t = 1_000_000)]
    iterations: u64,

    /// Random seed
    #[arg(long, default_value_t = 42)]
    seed: u64,

    /// Output chart to JSON file
    #[arg(long)]
    output: Option<String>,
}

// ---------------------------------------------------------------------------
// Position names
// ---------------------------------------------------------------------------

fn position_names(num_players: usize) -> &'static [&'static str] {
    match num_players {
        2 => &["SB", "BB"],
        3 => &["BTN", "SB", "BB"],
        4 => &["CO", "BTN", "SB", "BB"],
        _ => panic!("unsupported player count"),
    }
}

// ---------------------------------------------------------------------------
// Infoset storage
// ---------------------------------------------------------------------------

/// Infoset key: (player, prior_push_mask, canonical_hand_index)
/// For N players, prior_push_mask for player p has p bits (actions of players 0..p-1).
/// Total infosets per player p = 2^p * 169.
/// Total across all players = 169 * (1 + 2 + 4 + ... + 2^(N-1)) = 169 * (2^N - 1).
///
/// We flatten into a single array. Offset for player p:
///   player_offset(p) = 169 * (2^p - 1)
/// Within player p, offset = prior_mask * 169 + hand_index.

struct InfosetStore {
    /// regret_sum[infoset_idx][action]
    regret_sum: Vec<[f64; NUM_ACTIONS]>,
    /// strategy_sum[infoset_idx][action]
    strategy_sum: Vec<[f64; NUM_ACTIONS]>,
}

impl InfosetStore {
    fn new(num_players: usize) -> Self {
        // Total infosets = 169 * (2^N - 1)
        let total = NUM_CANONICAL * ((1usize << num_players) - 1);
        InfosetStore {
            regret_sum: vec![[0.0; NUM_ACTIONS]; total],
            strategy_sum: vec![[0.0; NUM_ACTIONS]; total],
        }
    }

    fn index(&self, player: usize, prior_mask: usize, hand_idx: usize) -> usize {
        let player_offset = NUM_CANONICAL * ((1usize << player) - 1);
        player_offset + prior_mask * NUM_CANONICAL + hand_idx
    }

    /// Regret-matching strategy for this infoset.
    fn current_strategy(&self, player: usize, prior_mask: usize, hand_idx: usize) -> [f64; NUM_ACTIONS] {
        let idx = self.index(player, prior_mask, hand_idx);
        let regrets = &self.regret_sum[idx];
        let mut strategy = [0.0; NUM_ACTIONS];
        let mut normalizing_sum = 0.0;
        for a in 0..NUM_ACTIONS {
            strategy[a] = if regrets[a] > 0.0 { regrets[a] } else { 0.0 };
            normalizing_sum += strategy[a];
        }
        if normalizing_sum > 0.0 {
            for a in 0..NUM_ACTIONS {
                strategy[a] /= normalizing_sum;
            }
        } else {
            // Default: uniform
            for a in 0..NUM_ACTIONS {
                strategy[a] = 1.0 / NUM_ACTIONS as f64;
            }
        }
        strategy
    }

    /// Average strategy (the equilibrium output).
    fn average_strategy(&self, player: usize, prior_mask: usize, hand_idx: usize) -> [f64; NUM_ACTIONS] {
        let idx = self.index(player, prior_mask, hand_idx);
        let sums = &self.strategy_sum[idx];
        let total: f64 = sums.iter().sum();
        if total > 0.0 {
            [sums[0] / total, sums[1] / total]
        } else {
            [0.5, 0.5]
        }
    }

    fn add_regret(&mut self, player: usize, prior_mask: usize, hand_idx: usize, action: usize, regret: f64) {
        let idx = self.index(player, prior_mask, hand_idx);
        self.regret_sum[idx][action] += regret;
    }

    fn add_strategy(&mut self, player: usize, prior_mask: usize, hand_idx: usize, strategy: &[f64; NUM_ACTIONS]) {
        let idx = self.index(player, prior_mask, hand_idx);
        for a in 0..NUM_ACTIONS {
            self.strategy_sum[idx][a] += strategy[a];
        }
    }
}

// ---------------------------------------------------------------------------
// Game state
// ---------------------------------------------------------------------------

/// Game config (immutable per solve).
struct GameConfig {
    num_players: usize,
    /// Stack in chips (1 chip = 0.5bb).
    stack_chips: u32,
    /// Blind contributions in chips: SB=1, BB=2.
    blinds: Vec<u32>,
    /// Ante per player in chips (1 chip = 0.5bb).
    ante_chips: f64,
}

impl GameConfig {
    fn new(num_players: usize, stack_bb: u32, ante_bb: f64) -> Self {
        let stack_chips = stack_bb * 2;
        // Blind assignments: second-to-last player is SB, last player is BB
        let mut blinds = vec![0u32; num_players];
        blinds[num_players - 2] = 1; // SB = 1 chip = 0.5bb
        blinds[num_players - 1] = 2; // BB = 2 chips = 1bb
        let ante_chips = ante_bb * 2.0;
        GameConfig {
            num_players,
            stack_chips,
            blinds,
            ante_chips,
        }
    }

    /// Total pot contribution for a player who folds (blinds + ante only).
    fn fold_contribution(&self, player: usize) -> f64 {
        self.blinds[player] as f64 + self.ante_chips
    }

}

// ---------------------------------------------------------------------------
// Deal & evaluate
// ---------------------------------------------------------------------------

/// Deal hole cards to N players, returning (cards_per_player, dead_mask).
fn deal_holes(rng: &mut SmallRng, num_players: usize) -> (Vec<[Card; 2]>, Hand) {
    let mut dead = Hand::new();
    let mut holes = Vec::with_capacity(num_players);
    for _ in 0..num_players {
        let c1 = draw_card(rng, dead);
        dead = dead.add(c1);
        let c2 = draw_card(rng, dead);
        dead = dead.add(c2);
        holes.push([c1, c2]);
    }
    (holes, dead)
}

/// Draw a random card not in `dead`.
fn draw_card(rng: &mut SmallRng, dead: Hand) -> Card {
    loop {
        let c = rng.gen_range(0..NUM_CARDS as u8);
        if !dead.contains(c) {
            return c;
        }
    }
}

/// Sample a 5-card board not conflicting with dead cards.
fn sample_board(rng: &mut SmallRng, dead: Hand) -> Hand {
    let mut board = Hand::new();
    let mut all_dead = dead;
    for _ in 0..5 {
        let c = draw_card(rng, all_dead);
        all_dead = all_dead.add(c);
        board = board.add(c);
    }
    board
}

/// Evaluate showdown among all-in players. Returns the payoff for each player
/// (relative to their starting stack, so negative means lost chips).
fn evaluate_showdown(
    config: &GameConfig,
    holes: &[[Card; 2]],
    push_mask: usize,
    board: Hand,
) -> Vec<f64> {
    let n = config.num_players;
    let mut payoffs = vec![0.0f64; n];

    // Identify pushers and folders
    let mut pushers: Vec<usize> = Vec::new();
    for p in 0..n {
        if push_mask & (1 << p) != 0 {
            pushers.push(p);
        }
    }

    let num_pushers = pushers.len();

    // Dead money from folders (they lose their blind + ante)
    let mut dead_money = 0.0f64;
    for p in 0..n {
        if push_mask & (1 << p) == 0 {
            dead_money += config.fold_contribution(p);
            payoffs[p] = -config.fold_contribution(p);
        }
    }

    if num_pushers == 0 {
        // Everyone folded — shouldn't happen in normal play, but handle it
        // BB wins the blinds by default
        let bb = n - 1;
        payoffs[bb] += dead_money;
        // Undo BB's loss
        payoffs[bb] += config.fold_contribution(bb);
        return payoffs;
    }

    if num_pushers == 1 {
        // One pusher wins all dead money
        let winner = pushers[0];
        // Pusher risked nothing beyond their blind/ante contribution (no caller)
        // They win dead_money and keep their own stack
        payoffs[winner] = dead_money; // net gain = dead money from folders
        return payoffs;
    }

    // Multiple pushers: showdown
    // Each pusher contributes their full stack (blinds/ante come from stack).
    // Total pot = dead_money (from folders) + num_pushers * stack_chips
    let total_pot = dead_money + num_pushers as f64 * config.stack_chips as f64;

    // Evaluate hands
    let mut strengths: Vec<(usize, Strength)> = Vec::with_capacity(num_pushers);
    for &p in &pushers {
        let hand = board.add(holes[p][0]).add(holes[p][1]);
        let s = evaluate(hand);
        strengths.push((p, s));
    }

    // Find the best strength
    let best = strengths.iter().map(|&(_, s)| s).max().unwrap();
    let winners: Vec<usize> = strengths
        .iter()
        .filter(|&&(_, s)| s == best)
        .map(|&(p, _)| p)
        .collect();

    let share = total_pot / winners.len() as f64;
    for &p in &pushers {
        // Each pusher's payoff = share_if_winner - their_contribution
        let contribution = config.stack_chips as f64;
        if winners.contains(&p) {
            payoffs[p] = share - contribution;
        } else {
            payoffs[p] = -contribution;
        }
    }

    payoffs
}

// ---------------------------------------------------------------------------
// MCCFR — External Sampling
// ---------------------------------------------------------------------------

/// Run one iteration of external sampling MCCFR.
/// Returns the expected payoff for the traverser.
fn cfr_external(
    config: &GameConfig,
    store: &mut InfosetStore,
    holes: &[[Card; 2]],
    hand_indices: &[usize],
    board: Hand,
    traverser: usize,
    current_player: usize,
    push_mask: usize,
    rng: &mut SmallRng,
) -> f64 {
    let n = config.num_players;

    // Check if all players have acted
    if current_player >= n {
        // Terminal node — evaluate
        let payoffs = evaluate_showdown(config, holes, push_mask, board);
        return payoffs[traverser];
    }

    // Check if everyone before current player folded and current player is BB
    // (the last player). If all previous players folded, BB wins automatically.
    // Actually, BB still gets to act — they can push (pointless but legal) or
    // "check" (which in push/fold = fold, meaning they just take the pot).
    // In push/fold, if everyone folds to BB, BB wins. No decision needed.
    if current_player == n - 1 && push_mask == 0 {
        // Everyone folded to BB. BB wins all the dead money (blinds + antes).
        let mut payoffs = vec![0.0f64; n];
        for p in 0..n - 1 {
            payoffs[p] = -config.fold_contribution(p);
        }
        // BB gains all the dead money. Their net = sum of others' contributions.
        let bb_gain: f64 = (0..n - 1).map(|p| config.fold_contribution(p)).sum();
        payoffs[n - 1] = bb_gain;
        return payoffs[traverser];
    }

    let hand_idx = hand_indices[current_player];
    let prior_mask = push_mask; // push_mask so far = actions of players before current

    let strategy = store.current_strategy(current_player, prior_mask, hand_idx);

    if current_player == traverser {
        // Traverser: explore both actions
        let mut action_values = [0.0f64; NUM_ACTIONS];

        // Push
        let new_mask_push = push_mask | (1 << current_player);
        action_values[PUSH] = cfr_external(
            config, store, holes, hand_indices, board,
            traverser, current_player + 1, new_mask_push, rng,
        );

        // Fold
        action_values[FOLD] = cfr_external(
            config, store, holes, hand_indices, board,
            traverser, current_player + 1, push_mask, rng,
        );

        // Node value under current strategy
        let node_value = strategy[PUSH] * action_values[PUSH] + strategy[FOLD] * action_values[FOLD];

        // Update regrets
        for a in 0..NUM_ACTIONS {
            let regret = action_values[a] - node_value;
            store.add_regret(current_player, prior_mask, hand_idx, a, regret);
        }

        node_value
    } else {
        // Opponent: sample one action according to strategy
        store.add_strategy(current_player, prior_mask, hand_idx, &strategy);

        let r: f64 = rng.gen();
        let action = if r < strategy[PUSH] { PUSH } else { FOLD };

        let new_mask = if action == PUSH {
            push_mask | (1 << current_player)
        } else {
            push_mask
        };

        cfr_external(
            config, store, holes, hand_indices, board,
            traverser, current_player + 1, new_mask, rng,
        )
    }
}

// ---------------------------------------------------------------------------
// Solver
// ---------------------------------------------------------------------------

fn solve(args: &Args) {
    assert!(
        args.players >= 2 && args.players <= 4,
        "players must be 2-4"
    );

    let config = GameConfig::new(args.players, args.stack, args.ante);
    let mut store = InfosetStore::new(args.players);
    let mut rng = SmallRng::seed_from_u64(args.seed);

    let names = position_names(args.players);

    eprintln!(
        "Push/Fold Solver: {} players, {}bb stack, {:.3}bb ante, {} iterations",
        args.players, args.stack, args.ante, args.iterations
    );

    for iter in 0..args.iterations {
        if iter > 0 && iter % 100_000 == 0 {
            eprintln!("iteration {}/{}", iter, args.iterations);
        }

        let traverser = (iter % args.players as u64) as usize;

        // Deal hole cards
        let (holes, dead) = deal_holes(&mut rng, args.players);

        // Compute canonical hand indices
        let hand_indices: Vec<usize> = holes
            .iter()
            .map(|h| canonical_hand(h[0], h[1]).index() as usize)
            .collect();

        // Sample board (used at terminal showdown nodes)
        let board = sample_board(&mut rng, dead);

        // Run MCCFR
        cfr_external(
            &config,
            &mut store,
            &holes,
            &hand_indices,
            board,
            traverser,
            0,     // current_player starts at 0
            0,     // push_mask starts empty
            &mut rng,
        );
    }

    eprintln!("iteration {}/{}", args.iterations, args.iterations);
    eprintln!("Solving complete.\n");

    // Print results
    print_results(&config, &store, names, args.iterations);

    // JSON output
    if let Some(ref path) = args.output {
        write_json(&config, &store, names, args, path);
        eprintln!("Chart written to {}", path);
    }
}

// ---------------------------------------------------------------------------
// Output formatting
// ---------------------------------------------------------------------------

const RANK_CHARS: [char; 13] = [
    '2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A',
];

/// Describe what a player is "facing" given a prior push mask.
fn facing_description(prior_mask: usize, names: &[&str], player: usize) -> String {
    if prior_mask == 0 {
        return "no action".to_string();
    }
    let pushers: Vec<&str> = (0..player)
        .filter(|&p| prior_mask & (1 << p) != 0)
        .map(|p| names[p])
        .collect();
    if pushers.is_empty() {
        "all fold".to_string()
    } else {
        format!("{} push", pushers.join("+"))
    }
}

/// Build the 13x13 grid for a given player and prior_mask situation.
/// Returns (grid[row][col], push_pct) where row=hi rank, col=lo rank.
/// Upper triangle (col > row after flipping) = suited, lower = offsuit, diagonal = pairs.
/// We index as grid[hi_rank_descending][lo_rank_descending] for display.
fn build_grid(
    store: &InfosetStore,
    player: usize,
    prior_mask: usize,
) -> ([[f64; 13]; 13], f64) {
    let mut grid = [[0.0f64; 13]; 13]; // grid[row][col]
    let mut total_push = 0.0f64;
    let mut total_combos = 0.0f64;

    for idx in 0..NUM_CANONICAL {
        let ch = CanonicalHand::from_index(idx as u8);
        let avg = store.average_strategy(player, prior_mask, idx);
        let push_freq = avg[PUSH];

        // Number of combos: pairs=6, suited=4, offsuit=12
        let combos = if ch.hi == ch.lo {
            6.0
        } else if ch.suited {
            4.0
        } else {
            12.0
        };
        total_push += push_freq * combos;
        total_combos += combos;

        // Grid position: rows and cols go from A(12) down to 2(0).
        // Display row r, col c:
        //   diagonal (r==c) = pair
        //   above diagonal (c > r in display, but we flip) = suited
        //   below diagonal = offsuit
        //
        // Standard poker grid: row = first rank, col = second rank
        //   (r, c) where r >= c: if r == c pair, above diag = suited, below = offsuit
        // Convention: row index = hi rank (A=top=row0), col = lo rank
        //   suited above diagonal means col < row in array indexing
        //
        // Let's use: grid[12-hi][12-lo] for suited (hi > lo),
        //            grid[12-lo][12-hi] for offsuit (hi > lo),
        //            grid[12-hi][12-hi] for pairs
        if ch.hi == ch.lo {
            grid[12 - ch.hi as usize][12 - ch.hi as usize] = push_freq;
        } else if ch.suited {
            // suited: above diagonal → row < col in display
            // row = 12 - hi, col = 12 - lo, since hi > lo → row < col ✓
            grid[12 - ch.hi as usize][12 - ch.lo as usize] = push_freq;
        } else {
            // offsuit: below diagonal → row > col in display
            grid[12 - ch.lo as usize][12 - ch.hi as usize] = push_freq;
        }
    }

    let push_pct = if total_combos > 0.0 {
        total_push / total_combos * 100.0
    } else {
        0.0
    };

    (grid, push_pct)
}

fn grid_char(freq: f64) -> char {
    if freq >= 0.80 {
        '■'
    } else if freq >= 0.50 {
        '▣'
    } else if freq >= 0.20 {
        '▨'
    } else {
        '□'
    }
}

/// Collect all (hand_name, push_freq) pairs for a situation, sorted by push_freq desc.
fn sorted_hands(
    store: &InfosetStore,
    player: usize,
    prior_mask: usize,
) -> Vec<(String, f64)> {
    let mut hands: Vec<(String, f64)> = (0..NUM_CANONICAL)
        .map(|idx| {
            let ch = CanonicalHand::from_index(idx as u8);
            let avg = store.average_strategy(player, prior_mask, idx);
            (ch.to_string(), avg[PUSH])
        })
        .collect();
    hands.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());
    hands
}

fn print_results(config: &GameConfig, store: &InfosetStore, names: &[&str], iterations: u64) {
    let n = config.num_players;

    println!("=== Push/Fold Chart ===");
    println!(
        "Players: {}, Stack: {}bb, Ante: {:.3}bb, Iterations: {}",
        n,
        config.stack_chips / 2,
        config.ante_chips / 2.0,
        iterations
    );
    println!();

    for player in 0..n {
        let num_states = 1usize << player; // 2^player possible prior masks
        for prior_mask in 0..num_states {
            // Skip states where everyone before folded AND we're BB (auto-win, no decision)
            // Actually BB does face decisions when someone pushed. If prior_mask == 0
            // and player == n-1, BB auto-wins, so skip.
            if player == n - 1 && prior_mask == 0 {
                continue;
            }

            let facing = facing_description(prior_mask, names, player);
            let (grid, push_pct) = build_grid(store, player, prior_mask);
            let action_word = if prior_mask == 0 { "Push" } else { "Push/Call" };

            println!(
                "--- {} (facing: {}) ---",
                names[player], facing
            );
            println!("{} range: {:.1}% of hands", action_word, push_pct);
            println!();

            // Print grid header
            print!("  ");
            for c in (0..13).rev() {
                print!("  {} ", RANK_CHARS[c]);
            }
            println!("   (suited above diagonal, offsuit below)");

            for r in 0..13 {
                let rank_idx = 12 - r;
                print!("{} ", RANK_CHARS[rank_idx]);
                for c in 0..13 {
                    let freq = grid[r][c];
                    print!("  {} ", grid_char(freq));
                }
                println!();
            }
            println!();

            // Top pushes and top folds
            let hands = sorted_hands(store, player, prior_mask);
            let top_pushes: Vec<String> = hands
                .iter()
                .take(10)
                .filter(|(_, f)| *f > 0.01)
                .map(|(name, f)| format!("{}({:.0}%)", name, f * 100.0))
                .collect();
            let top_folds: Vec<String> = hands
                .iter()
                .rev()
                .take(10)
                .filter(|(_, f)| *f < 0.99)
                .map(|(name, f)| format!("{}({:.1}%)", name, f * 100.0))
                .collect();

            println!("Top pushes: {}", top_pushes.join(", "));
            println!("Top folds:  {}", top_folds.join(", "));
            println!();
        }
    }
}

// ---------------------------------------------------------------------------
// JSON output
// ---------------------------------------------------------------------------

fn write_json(
    config: &GameConfig,
    store: &InfosetStore,
    names: &[&str],
    args: &Args,
    path: &str,
) {
    use std::io::Write;

    let file = File::create(path).expect("failed to create output file");
    let mut w = BufWriter::new(file);

    write!(w, "{{\n").unwrap();
    write!(w, "  \"players\": {},\n", args.players).unwrap();
    write!(w, "  \"stack_bb\": {},\n", args.stack).unwrap();
    write!(w, "  \"ante_bb\": {},\n", args.ante).unwrap();
    write!(w, "  \"iterations\": {},\n", args.iterations).unwrap();
    write!(w, "  \"seed\": {},\n", args.seed).unwrap();
    write!(w, "  \"positions\": [\n").unwrap();

    let n = config.num_players;
    let mut first_pos = true;

    for player in 0..n {
        if !first_pos {
            write!(w, ",\n").unwrap();
        }
        first_pos = false;

        write!(w, "    {{\n").unwrap();
        write!(w, "      \"name\": \"{}\",\n", names[player]).unwrap();
        write!(w, "      \"index\": {},\n", player).unwrap();
        write!(w, "      \"situations\": [\n").unwrap();

        let num_states = 1usize << player;
        let mut first_sit = true;

        for prior_mask in 0..num_states {
            if player == n - 1 && prior_mask == 0 {
                continue;
            }

            if !first_sit {
                write!(w, ",\n").unwrap();
            }
            first_sit = false;

            let facing = facing_description(prior_mask, names, player);
            let (_, push_pct) = build_grid(store, player, prior_mask);

            write!(w, "        {{\n").unwrap();
            write!(w, "          \"facing\": \"{}\",\n", facing).unwrap();
            write!(w, "          \"push_pct\": {:.1},\n", push_pct).unwrap();
            write!(w, "          \"hands\": [\n").unwrap();

            let mut first_hand = true;
            for idx in 0..NUM_CANONICAL {
                let ch = CanonicalHand::from_index(idx as u8);
                let avg = store.average_strategy(player, prior_mask, idx);

                if !first_hand {
                    write!(w, ",\n").unwrap();
                }
                first_hand = false;

                write!(
                    w,
                    "            {{\"hand\": \"{}\", \"push\": {:.4}}}",
                    ch.to_string(),
                    avg[PUSH]
                )
                .unwrap();
            }

            write!(w, "\n          ]\n").unwrap();
            write!(w, "        }}").unwrap();
        }

        write!(w, "\n      ]\n").unwrap();
        write!(w, "    }}").unwrap();
    }

    write!(w, "\n  ]\n").unwrap();
    write!(w, "}}\n").unwrap();
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

fn main() {
    let args = Args::parse();
    solve(&args);
}
