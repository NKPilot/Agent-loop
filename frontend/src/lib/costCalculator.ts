/**
 * Token-to-cost estimation utilities.
 *
 * Default rates are based on gpt-4o-mini pricing.
 * All calculations are client-side for display purposes.
 */

import type { CostRates } from "./eventTypes";

// ── Default rates ─────────────────────────────────────────────────────

export const DEFAULT_COST_RATES: CostRates = {
  promptPer1K: 0.003,
  completionPer1K: 0.015,
};

// ── Calculation ───────────────────────────────────────────────────────

/**
 * Calculate the estimated cost in USD for a given token usage.
 *
 * @param promptTokens - Number of prompt tokens used
 * @param completionTokens - Number of completion tokens generated
 * @param rates - Optional custom cost rates (defaults to gpt-4o-mini)
 * @returns Estimated cost in USD
 */
export function calculateCost(
  promptTokens: number,
  completionTokens: number,
  rates: CostRates = DEFAULT_COST_RATES
): number {
  const promptCost = (promptTokens / 1000) * rates.promptPer1K;
  const completionCost = (completionTokens / 1000) * rates.completionPer1K;
  return promptCost + completionCost;
}

// ── Formatting ────────────────────────────────────────────────────────

/**
 * Format a cost value as a USD string with 3 decimal places.
 *
 * @param cost - Cost in USD
 * @returns Formatted string like "$0.042"
 */
export function formatCost(cost: number): string {
  return `$${cost.toFixed(3)}`;
}

/**
 * Format a token count with thousands separators.
 *
 * @param count - Number of tokens
 * @returns Formatted string like "1,234"
 */
export function formatTokens(count: number): string {
  return count.toLocaleString("en-US");
}
