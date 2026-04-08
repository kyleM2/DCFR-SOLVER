/// Complete tree-walk extraction for preflop charts.
///
/// Recursively walks EVERY decision node in the game tree and extracts
/// the trained strategy from the blueprint. Guarantees zero missing spots,
/// unlike the manual chart extraction which only covers "clean" paths
/// (everyone between folds).
///
/// Usage: load an existing .bin blueprint, then call `extract_tree()`.
/// No retraining needed — the blueprint already has all strategies.

use crate::iso::CanonicalHand;
use crate::preflop::{
    ActionProb, HandStrategy, PreflopAction, PreflopBlueprint, PreflopInfoKey,
    PreflopNodeType, PreflopSpot, PreflopState, POSITION_NAMES,
};

// ---------------------------------------------------------------------------
// Output types
// ---------------------------------------------------------------------------

/// Extended spot with metadata for bot matching.
#[derive(Debug, Clone, serde::Serialize)]
pub struct TreeSpot {
    /// Human-readable spot name (e.g. "CO | UTG open > HJ call")
    pub spot_name: String,
    /// Acting player position name
    pub position: String,
    /// Acting player position index (0=UTG, 1=HJ, 2=CO, 3=BTN, 4=SB, 5=BB)
    pub position_idx: usize,
    /// Action-index history from root (for exact blueprint key matching)
    pub history: Vec<u8>,
    /// Human-readable action line (e.g. "UTG open > HJ call")
    pub line: String,
    /// Available actions at this node
    pub available_actions: Vec<String>,
    /// Per-hand strategy (169 canonical hands)
    pub hands: Vec<HandStrategy>,
}

// ---------------------------------------------------------------------------
// Internal bookkeeping
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
struct ActionRecord {
    position: usize,
    action: PreflopAction,
    raise_depth: u8, // state.n_raises BEFORE this action was applied
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Extract ALL decision nodes via recursive tree walk.
///
/// # Arguments
/// * `blueprint`    – trained preflop blueprint (.bin)
/// * `num_players`  – active players (2..6)
/// * `stack_chips`  – starting stack in chips (1 chip = 0.5 bb)
/// * `max_n_raises` – 2 = up to facing 3-bet, 3 = up to facing 4-bet
pub fn extract_tree(
    blueprint: &PreflopBlueprint,
    num_players: usize,
    stack_chips: i32,
    max_n_raises: u8,
) -> Vec<TreeSpot> {
    let root = PreflopState::new_generic(
        num_players,
        stack_chips,
        blueprint.config.clone(),
    );
    let mut spots = Vec::new();
    let mut history = Vec::new();
    let mut action_log: Vec<ActionRecord> = Vec::new();

    walk(
        &root,
        blueprint,
        &mut history,
        &mut action_log,
        max_n_raises,
        &mut spots,
    );

    spots
}

/// Convenience wrapper returning `PreflopSpot` (backward-compatible format).
pub fn extract_tree_compat(
    blueprint: &PreflopBlueprint,
    num_players: usize,
    stack_chips: i32,
    max_n_raises: u8,
) -> Vec<PreflopSpot> {
    extract_tree(blueprint, num_players, stack_chips, max_n_raises)
        .into_iter()
        .map(|t| PreflopSpot {
            spot_name: t.spot_name,
            hands: t.hands,
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Tree walk
// ---------------------------------------------------------------------------

fn walk(
    state: &PreflopState,
    blueprint: &PreflopBlueprint,
    history: &mut Vec<u8>,
    action_log: &mut Vec<ActionRecord>,
    max_n_raises: u8,
    spots: &mut Vec<TreeSpot>,
) {
    match state.node_type() {
        PreflopNodeType::TerminalFold(_) | PreflopNodeType::TerminalShowdown => return,
        PreflopNodeType::Decision(player) => {
            let p = player as usize;
            let actions = state.actions();

            // --- extract this node's strategy ---
            let (spot_name, line) = build_label(p, action_log);
            let available_actions: Vec<String> =
                actions.iter().map(|a| format!("{}", a)).collect();
            let hands = extract_hands(blueprint, history, &actions);

            spots.push(TreeSpot {
                spot_name,
                position: POSITION_NAMES[p].to_string(),
                position_idx: p,
                history: history.clone(),
                line,
                available_actions,
                hands,
            });

            // --- recurse into each child action ---
            for (idx, &action) in actions.iter().enumerate() {
                let child = state.apply(action);

                // Don't recurse past max raise depth
                if child.n_raises > max_n_raises {
                    continue;
                }

                history.push(idx as u8);
                action_log.push(ActionRecord {
                    position: p,
                    action,
                    raise_depth: state.n_raises,
                });

                walk(&child, blueprint, history, action_log, max_n_raises, spots);

                history.pop();
                action_log.pop();
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Hand extraction
// ---------------------------------------------------------------------------

fn extract_hands(
    blueprint: &PreflopBlueprint,
    history: &[u8],
    actions: &[PreflopAction],
) -> Vec<HandStrategy> {
    (0..169u8)
        .map(|idx| {
            let ch = CanonicalHand::from_index(idx);
            let key = PreflopInfoKey {
                bucket: idx,
                history: history.to_vec(),
            };
            let action_probs = match blueprint.entries.get(&key) {
                Some(entry) => {
                    let avg = entry.average_strategy();
                    actions
                        .iter()
                        .zip(avg.iter())
                        .map(|(a, &p)| ActionProb {
                            action: format!("{}", a),
                            prob: p,
                        })
                        .collect()
                }
                None => vec![],
            };
            HandStrategy {
                hand: ch.to_string(),
                actions: action_probs,
            }
        })
        .collect()
}

// ---------------------------------------------------------------------------
// Spot labeling
// ---------------------------------------------------------------------------

/// Build a human-readable label for a decision node.
///
/// Returns `(spot_name, line)`:
/// - spot_name: `"{POSITION} | {line}"` or `"{POSITION} RFI"`
/// - line: the action sequence part (empty for RFI)
///
/// Examples:
/// - `("UTG RFI", "")`
/// - `("BB | SB limp", "SB limp")`
/// - `("SB | SB limp > BB raise", "SB limp > BB raise")`
/// - `("CO | UTG open > HJ call", "UTG open > HJ call")`
/// - `("UTG | UTG open > BTN 3bet", "UTG open > BTN 3bet")`
fn build_label(actor: usize, log: &[ActionRecord]) -> (String, String) {
    let name = POSITION_NAMES[actor];

    // Collect significant (non-fold) actions
    let sig: Vec<&ActionRecord> = log
        .iter()
        .filter(|r| !matches!(r.action, PreflopAction::Fold))
        .collect();

    if sig.is_empty() {
        return (format!("{} RFI", name), String::new());
    }

    let mut parts = Vec::new();
    for (i, rec) in sig.iter().enumerate() {
        let pos = POSITION_NAMES[rec.position];
        let label = action_label(&rec.action, rec.raise_depth, &sig[..i]);
        parts.push(format!("{} {}", pos, label));
    }

    let line = parts.join(" > ");
    (format!("{} | {}", name, line), line)
}

/// Describe an action in human-readable form based on raise depth context.
fn action_label(action: &PreflopAction, raise_depth: u8, prior: &[&ActionRecord]) -> String {
    match action {
        PreflopAction::Fold => "fold".into(),
        PreflopAction::Check => "check".into(),
        PreflopAction::Call => {
            if raise_depth == 0 {
                "limp".into()
            } else {
                "call".into()
            }
        }
        PreflopAction::Raise(_) => {
            let has_limpers = prior.iter().any(|r| {
                matches!(r.action, PreflopAction::Call) && r.raise_depth == 0
            });
            match raise_depth {
                0 if has_limpers => "raise".into(),
                0 => "open".into(),
                1 => "3bet".into(),
                2 => "4bet".into(),
                n => format!("{}bet", n + 1),
            }
        }
        PreflopAction::AllIn => {
            if raise_depth == 0 {
                "shove".into()
            } else {
                "allin".into()
            }
        }
    }
}
