//! Preflop trainer fork with configurable tax formula.
//!
//! Phase 2 of the preflop_fix investigation. This is a standalone binary
//! that forks the `cfr_external` method from `src/preflop.rs` to allow
//! swapping the OOP-pot-tax formula without modifying existing files.
//!
//! Background (see preflop_fix/phase1b_ablation/FINDINGS.md):
//! The production preflop solver over-opens BTN (85.98% total at 6p 100bb)
//! and produces non-monotonic opens like 84o at 71.64%. The root cause is
//! the hardcoded showdown-terminal tax formula at src/preflop.rs:887-890:
//!
//!     let gap = postflop_rank(ip) - postflop_rank(oop);
//!     let scaled_tax = base_tax * gap as f32 / 5.0;
//!
//! For BTN-vs-SB the gap is 5, so BTN receives the maximum IP bonus.
//! This over-rewards BTN relative to UTG/HJ/CO and turns losing opens
//! into profitable ones.
//!
//! This fork exposes a `TaxMode` enum:
//!   - None     : no tax at all
//!   - Flat     : tax = base_tax (no gap scaling)
//!   - Original : tax = base_tax * gap / 5.0 (reference, matches prod)
//!
//! Other than the tax computation, this trainer is a direct copy of
//! `PreflopTrainer::{train_generic, cfr_external, deal_holes_for,
//! draw_excluding, sample_board}` from src/preflop.rs.
//!
//! Usage:
//!   target/release/preflop_fixed \
//!     --stack 100 --players 6 --iterations 2000000 \
//!     --tax-mode flat --base-tax 0.10 \
//!     --output out.bin --chart-output out.json

use clap::Parser;
use dcfr_solver::card::{Card, Hand, NUM_CARDS};
use dcfr_solver::infoset::RegretEntry;
use dcfr_solver::iso::canonical_hand;
use dcfr_solver::preflop::{
    PreflopBetConfig, PreflopBlueprint, PreflopInfoKey, PreflopNodeType, PreflopState,
    NUM_PLAYERS,
};
use rand::rngs::SmallRng;
use rand::{Rng, SeedableRng};
use std::fs::File;
use std::io::BufWriter;
use std::str::FromStr;

// ---------------------------------------------------------------------------
// TaxMode — the only divergence from upstream
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
enum TaxMode {
    /// No showdown-terminal tax transfer at all.
    None,
    /// Flat tax = base_tax regardless of position gap.
    /// IP and OOP are still identified, but the transfer is constant.
    Flat,
    /// Reference / upstream: tax = base_tax * gap / 5.0.
    /// BTN-vs-SB (gap=5) gets full base_tax; BTN-vs-BB (gap=4) gets 0.8 * base_tax, etc.
    Original,
    /// Capped: scaled = base_tax * min(gap, cap) / cap.
    /// Clamps the top end so BTN-vs-SB and BTN-vs-BB get identical tax.
    /// cap=2 makes everyone with gap>=2 equal; cap=5 degenerates to Original.
    Capped { cap: u32 },
    /// Shifted: scaled = base_tax * max(0, gap - shift) / max(1, 5 - shift).
    /// Zeros out the lowest gaps (protects SB-vs-BB at shift>=1) and linearly
    /// interpolates the rest up to base_tax at gap=5.
    Shift { shift: u32 },
    /// Quadratic: scaled = base_tax * sqrt(gap / 5.0).
    /// Sublinear in gap — flatter than Original but still rewarding BTN.
    Quadratic,
    /// PerGap: explicit per-gap coefficients indexed 0..=5.
    /// scaled = coeffs[gap] * base_tax.
    PerGap { coeffs: [f32; 6] },
}

impl FromStr for TaxMode {
    type Err = String;
    fn from_str(s: &str) -> Result<Self, String> {
        let s = s.to_ascii_lowercase();
        match s.as_str() {
            "none" | "off" | "0" => return Ok(TaxMode::None),
            "flat" => return Ok(TaxMode::Flat),
            "original" | "orig" | "gap5" => return Ok(TaxMode::Original),
            "quadratic" | "quad" | "sqrt" => return Ok(TaxMode::Quadratic),
            _ => {}
        }
        if let Some(rest) = s.strip_prefix("capped") {
            // capped:3 | capped3
            let cap_str = rest.trim_start_matches(':').trim_start_matches('=');
            if cap_str.is_empty() {
                return Ok(TaxMode::Capped { cap: 2 });
            }
            let cap: u32 = cap_str
                .parse()
                .map_err(|e| format!("capped cap: {}", e))?;
            return Ok(TaxMode::Capped { cap: cap.max(1) });
        }
        if let Some(rest) = s.strip_prefix("shift") {
            let shift_str = rest.trim_start_matches(':').trim_start_matches('=');
            if shift_str.is_empty() {
                return Ok(TaxMode::Shift { shift: 1 });
            }
            let shift: u32 = shift_str
                .parse()
                .map_err(|e| format!("shift amount: {}", e))?;
            if shift >= 5 {
                return Err("shift must be < 5".into());
            }
            return Ok(TaxMode::Shift { shift });
        }
        if let Some(rest) = s.strip_prefix("pergap") {
            // pergap:0,0.05,0.10,0.15,0.20,0.25
            let nums = rest.trim_start_matches(':').trim_start_matches('=');
            let parts: Vec<&str> = nums.split(',').collect();
            if parts.len() != 6 {
                return Err(format!(
                    "pergap needs 6 comma-separated coefficients, got {}",
                    parts.len()
                ));
            }
            let mut coeffs = [0.0f32; 6];
            for (i, p) in parts.iter().enumerate() {
                coeffs[i] = p.parse().map_err(|e| format!("pergap[{}]: {}", i, e))?;
            }
            return Ok(TaxMode::PerGap { coeffs });
        }
        Err(format!(
            "unknown tax mode '{}' (expected: none | flat | original | capped:N | shift:N | quadratic | pergap:c0,c1,..,c5)",
            s
        ))
    }
}

// ---------------------------------------------------------------------------
// FixedTrainer — forked PreflopTrainer
// ---------------------------------------------------------------------------

struct FixedTrainer {
    blueprint: PreflopBlueprint,
    rng: SmallRng,
    board_samples: usize,
    tax_mode: TaxMode,
    base_tax: f32,
}

impl FixedTrainer {
    fn new(config: PreflopBetConfig, seed: u64, tax_mode: TaxMode, base_tax: f32) -> Self {
        FixedTrainer {
            blueprint: PreflopBlueprint::new(config),
            rng: SmallRng::seed_from_u64(seed),
            board_samples: 10,
            tax_mode,
            base_tax,
        }
    }

    fn draw_excluding(&mut self, dead: Hand) -> Card {
        loop {
            let c = self.rng.gen_range(0..NUM_CARDS as u8);
            if !dead.contains(c) {
                return c;
            }
        }
    }

    fn deal_holes_for(&mut self, positions: &[usize]) -> [Hand; NUM_PLAYERS] {
        let mut holes = [Hand::new(); NUM_PLAYERS];
        let mut dead = Hand::new();
        for &p in positions {
            let c1 = self.draw_excluding(dead);
            dead = dead.add(c1);
            let c2 = self.draw_excluding(dead);
            dead = dead.add(c2);
            holes[p] = Hand::new().add(c1).add(c2);
        }
        holes
    }

    fn sample_board(&mut self, dead: Hand) -> Hand {
        let mut board = Hand::new();
        let mut dead = dead;
        for _ in 0..5 {
            let c = self.draw_excluding(dead);
            board = board.add(c);
            dead = dead.add(c);
        }
        board
    }

    /// Generic N-player training (mirrors PreflopTrainer::train_generic).
    fn train_generic(&mut self, iterations: u64, num_players: usize, stack_chips: i32) {
        let first_active = NUM_PLAYERS - num_players;
        let active_positions: Vec<usize> = (first_active..NUM_PLAYERS).collect();

        for i in 0..iterations {
            if i > 0 && i % 100_000 == 0 {
                eprintln!(
                    "  iteration {}/{} ({} info sets)",
                    i,
                    iterations,
                    self.blueprint.entries.len()
                );
            }

            let holes = self.deal_holes_for(&active_positions);
            let traverser = active_positions[i as usize % num_players] as u8;

            let mut state = PreflopState::new_generic(
                num_players,
                stack_chips,
                self.blueprint.config.clone(),
            );
            for &p in &active_positions {
                state.holes[p] = holes[p];
            }

            let mut history = Vec::new();
            self.cfr_external(&state, traverser, &mut history);
            self.blueprint.iterations += 1;
        }
    }

    /// Compute the per-showdown tax under the current TaxMode.
    /// Returns Some((ip_idx, oop_idx, tax_chips)) or None if no tax applies.
    fn compute_tax(&self, state: &PreflopState) -> Option<(usize, usize, f32)> {
        if matches!(self.tax_mode, TaxMode::None) {
            return None;
        }
        if self.base_tax < 0.001 {
            return None;
        }
        if state.active_count() != 2 {
            return None;
        }
        let active: Vec<usize> = (0..NUM_PLAYERS)
            .filter(|&i| !state.folded[i])
            .collect();
        if active.len() != 2 {
            return None;
        }

        // Postflop action order: SB → BB → UTG → HJ → CO → BTN.
        // Higher rank = acts later postflop = more IP.
        let postflop_rank = |p: usize| -> usize {
            match p {
                3 => 5, // BTN
                2 => 4, // CO
                1 => 3, // HJ
                0 => 2, // UTG
                5 => 1, // BB (IP vs SB only)
                4 => 0, // SB
                _ => 0,
            }
        };
        let (ip, oop) = if postflop_rank(active[0]) > postflop_rank(active[1]) {
            (active[0], active[1])
        } else {
            (active[1], active[0])
        };

        let gap = postflop_rank(ip) - postflop_rank(oop);
        let scaled = match &self.tax_mode {
            TaxMode::None => 0.0,
            TaxMode::Flat => self.base_tax,
            TaxMode::Original => self.base_tax * (gap as f32) / 5.0,
            TaxMode::Capped { cap } => {
                let cap = *cap as usize;
                let clamped = gap.min(cap);
                self.base_tax * (clamped as f32) / (cap as f32)
            }
            TaxMode::Shift { shift } => {
                let shift = *shift as usize;
                if gap <= shift {
                    0.0
                } else {
                    let num = (gap - shift) as f32;
                    let den = (5 - shift).max(1) as f32;
                    self.base_tax * num / den
                }
            }
            TaxMode::Quadratic => self.base_tax * ((gap as f32) / 5.0).sqrt(),
            TaxMode::PerGap { coeffs } => {
                let idx = gap.min(5);
                self.base_tax * coeffs[idx]
            }
        };

        let total_pot: i32 = state.bets.iter().sum();
        let tax = (total_pot as f32) * scaled;
        Some((ip, oop, tax))
    }

    /// Main CFR recursion. Mirrors PreflopTrainer::cfr_external exactly
    /// EXCEPT for the tax computation on the showdown terminal branch.
    fn cfr_external(
        &mut self,
        state: &PreflopState,
        traverser: u8,
        history: &mut Vec<u8>,
    ) -> f32 {
        match state.node_type() {
            PreflopNodeType::TerminalFold(winner) => {
                let payoffs = state.payoff_fold(winner);
                payoffs[traverser as usize]
            }
            PreflopNodeType::TerminalShowdown => {
                let mut dead = Hand::new();
                for p in 0..NUM_PLAYERS {
                    dead = dead.union(state.holes[p]);
                }

                let tax_info = self.compute_tax(state);
                let n = self.board_samples;
                let mut total = 0.0f32;

                for _ in 0..n {
                    let board = self.sample_board(dead);
                    let mut payoffs = state.payoff_showdown(board);
                    if let Some((ip, oop, tax)) = tax_info {
                        payoffs[oop] -= tax;
                        payoffs[ip] += tax;
                    }
                    total += payoffs[traverser as usize];
                }
                total / n as f32
            }
            PreflopNodeType::Decision(player) => {
                let actions = state.actions();
                let n_actions = actions.len();

                let hole = state.holes[player as usize];
                let cards: Vec<Card> = hole.iter().collect();
                let bucket = canonical_hand(cards[0], cards[1]).index();

                let key = PreflopInfoKey {
                    bucket,
                    history: history.clone(),
                };

                // Inline get_or_create (PreflopBlueprint::get_or_create is private upstream
                // but `entries` is pub, so we can do it ourselves).
                let strategy = {
                    let entry = self
                        .blueprint
                        .entries
                        .entry(key.clone())
                        .or_insert_with(|| RegretEntry::new(n_actions));
                    entry.current_strategy()
                };

                if player == traverser {
                    let mut action_values = vec![0.0f32; n_actions];
                    let mut node_value = 0.0f32;

                    for (a, &action) in actions.iter().enumerate() {
                        let child = state.apply(action);
                        history.push(a as u8);
                        let value = self.cfr_external(&child, traverser, history);
                        history.pop();
                        action_values[a] = value;
                        node_value += strategy[a] * value;
                    }

                    let weight = self.blueprint.iterations as f32 + 1.0;
                    let entry = self
                        .blueprint
                        .entries
                        .get_mut(&key)
                        .expect("entry just inserted");
                    for a in 0..n_actions {
                        entry.regrets[a] =
                            (entry.regrets[a] + action_values[a] - node_value).max(0.0);
                        entry.cum_strategy[a] += weight * strategy[a];
                    }

                    node_value
                } else {
                    let action_idx = sample_action(&strategy, &mut self.rng);
                    let child = state.apply(actions[action_idx]);
                    history.push(action_idx as u8);
                    let value = self.cfr_external(&child, traverser, history);
                    history.pop();
                    value
                }
            }
        }
    }
}

fn sample_action(strategy: &[f32], rng: &mut SmallRng) -> usize {
    let r: f32 = rng.gen();
    let mut cum = 0.0;
    for (i, &p) in strategy.iter().enumerate() {
        cum += p;
        if r < cum {
            return i;
        }
    }
    strategy.len() - 1
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

#[derive(Parser)]
#[command(about = "Preflop trainer fork with configurable tax formula (Phase 2)")]
struct Cli {
    /// Effective stack in big blinds
    #[arg(long, default_value_t = 100)]
    stack: i32,

    /// Number of active players (2..6)
    #[arg(long, default_value_t = 6)]
    players: usize,

    /// Training iterations
    #[arg(long, default_value_t = 2_000_000)]
    iterations: u64,

    /// RNG seed
    #[arg(long, default_value_t = 42)]
    seed: u64,

    /// Tax mode: none | flat | original
    #[arg(long, default_value = "flat")]
    tax_mode: String,

    /// Base tax (before mode scaling). 0.10 with flat ≈ reference at gap=2.
    #[arg(long, default_value_t = 0.10)]
    base_tax: f32,

    /// Board samples per showdown terminal
    #[arg(long, default_value_t = 10)]
    board_samples: usize,

    /// Output blueprint (.bin)
    #[arg(long)]
    output: String,

    /// Output chart JSON (optional, only valid for players=6)
    #[arg(long)]
    chart_output: Option<String>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cli = Cli::parse();
    let tax_mode: TaxMode = cli.tax_mode.parse()?;

    if !(2..=6).contains(&cli.players) {
        return Err(format!("players must be in 2..=6, got {}", cli.players).into());
    }
    if cli.chart_output.is_some() && cli.players != 6 {
        eprintln!(
            "warning: chart-output only extracts 6-max RFI spots; \
             with players={} the chart will be incomplete",
            cli.players
        );
    }

    // 1 chip = 0.5bb
    let stack_chips = cli.stack * 2;
    let config = PreflopBetConfig::for_stack(cli.stack);

    eprintln!("=== Preflop-Fixed Trainer (Phase 2) ===");
    eprintln!(
        "Players: {}, Stack: {}bb ({} chips)",
        cli.players, cli.stack, stack_chips
    );
    eprintln!("Iterations: {}, Seed: {}", cli.iterations, cli.seed);
    eprintln!(
        "Tax mode: {:?}, Base tax: {}, Board samples: {}",
        tax_mode, cli.base_tax, cli.board_samples
    );

    let mut trainer = FixedTrainer::new(config, cli.seed, tax_mode, cli.base_tax);
    trainer.board_samples = cli.board_samples;

    let start = std::time::Instant::now();
    trainer.train_generic(cli.iterations, cli.players, stack_chips);
    let elapsed = start.elapsed().as_secs_f32();
    eprintln!(
        "Training complete in {:.2}s ({} info sets, {} iterations)",
        elapsed,
        trainer.blueprint.entries.len(),
        trainer.blueprint.iterations,
    );

    // Save blueprint
    {
        let file = File::create(&cli.output)?;
        let mut writer = BufWriter::new(file);
        trainer.blueprint.save(&mut writer)?;
        eprintln!("Saved blueprint → {}", cli.output);
    }

    // Save charts (6-max only)
    if let Some(chart_path) = cli.chart_output {
        let charts = trainer.blueprint.extract_charts();
        let file = File::create(&chart_path)?;
        serde_json::to_writer_pretty(file, &charts)?;
        eprintln!("Saved charts → {}", chart_path);
    }

    Ok(())
}
