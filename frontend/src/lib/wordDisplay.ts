// Shared familiarity label/color mapping - used by both the per-analysis
// results page and the profile "Known Words" management page, so the
// wording/colors can't drift between the two views of the same data.
export function familiarityLabel(score: number | null | undefined): string {
    if (score === null || score === undefined) return 'Unknown';
    const labels: Record<number, string> = {
        1: 'Seen it',
        2: 'Recognize',
        3: 'Know it',
        4: 'Know well',
        5: 'Mastered',
    };
    return labels[score] ?? 'Unknown';
}

export function familiarityColor(score: number | null | undefined): string {
    if (score === null || score === undefined) return 'bg-gray-100 text-gray-600';
    const colors: Record<number, string> = {
        1: 'bg-red-100 text-red-700',
        2: 'bg-orange-100 text-orange-700',
        3: 'bg-yellow-100 text-yellow-700',
        4: 'bg-green-100 text-green-700',
        5: 'bg-emerald-100 text-emerald-700',
    };
    return colors[score] ?? 'bg-gray-100 text-gray-600';
}

// Bucket label/color mapping - the "which pass produced this row" axis,
// orthogonal to evidence tier below. Three buckets going forward: best-
// guess segmentation (dag/overlay/unknown - the DP's single chosen path,
// including its own "unknown" fallback), Extra match (extra_match - a
// full-segmentation candidate that existed but wasn't chosen), Repeated
// sequence (repeated_sequence - a tokenizer/repeated-substring find).
// Legacy pre-rework values map onto their semantic successor so old
// analyses still bucket sensibly: trie -> main segmentation (same meaning
// as dag, pre-rename), longest_match_only -> extra match, token -> repeated
// sequence.
export function bucketLabel(source: string | null | undefined): string {
    if (!source) return 'Main segmentation';
    const labels: Record<string, string> = {
        dag: 'Main segmentation',
        overlay: 'Main segmentation',
        unknown: 'Main segmentation',
        trie: 'Main segmentation',
        extra_match: 'Extra match',
        longest_match_only: 'Extra match',
        repeated_sequence: 'Repeated sequence',
        token: 'Repeated sequence',
    };
    return labels[source] ?? source;
}

export function bucketColor(source: string | null | undefined): string {
    if (!source) return 'bg-blue-100 text-blue-700';
    const colors: Record<string, string> = {
        dag: 'bg-blue-100 text-blue-700',
        overlay: 'bg-blue-100 text-blue-700',
        unknown: 'bg-blue-100 text-blue-700',
        trie: 'bg-blue-100 text-blue-700',
        extra_match: 'bg-amber-100 text-amber-700',
        longest_match_only: 'bg-amber-100 text-amber-700',
        repeated_sequence: 'bg-purple-100 text-purple-700',
        token: 'bg-purple-100 text-purple-700',
    };
    return colors[source] ?? 'bg-gray-100 text-gray-600';
}

// Evidence-tier label/color mapping - the primary per-row chip (results
// table/cards, ReadingView's "Color by" mode). Orthogonal to bucket above:
// bucket answers "which pass produced this row" (bucketLabel/bucketColor,
// still shown via the BUCKETS filter bar and the per-row bucket chip);
// evidence tier answers "why should a user trust this as a real word"
// (User > Dictionary > Corpus > None - see WordResult.evidence_tier's
// docstring, schemas.py, for the resolution hierarchy).
export function evidenceTierLabel(tier: string | null | undefined): string {
    if (!tier) return 'None';
    const labels: Record<string, string> = {
        user: 'Your word',
        dictionary: 'Dictionary',
        corpus: 'Corpus',
        unknown: 'None',
    };
    return labels[tier] ?? tier;
}

export function evidenceTierColor(tier: string | null | undefined): string {
    if (!tier) return 'bg-gray-100 text-gray-600';
    const colors: Record<string, string> = {
        // Matches overlay's existing color (bucketColor) - both mean "this
        // word exists in segmentation because of the user's own data."
        user: 'bg-indigo-100 text-indigo-700',
        // Matches dag/trie's existing color - Dictionary is the direct
        // successor to what "segmenter" meant in the common case (a real
        // dictionary word, not just something the DP happened to route
        // through).
        dictionary: 'bg-blue-100 text-blue-700',
        // A new, distinct color (not reused from bucketColor) - "real
        // corpus frequency, but not curated by HSK/CC-CEDICT" is a
        // genuinely different signal from either Dictionary or None,
        // and needs its own color to read as a third thing at a glance.
        corpus: 'bg-teal-100 text-teal-700',
        unknown: 'bg-gray-100 text-gray-600',
    };
    return colors[tier] ?? 'bg-gray-100 text-gray-600';
}

// Finer-grained counterpart to evidenceTierLabel/evidenceTierColor above,
// used only by ReadingView's "Color by: Source" mode - splits that scale's
// "Dictionary" tier into which curated source actually backs the word
// (HSK vs CC-CEDICT), per AnalysisSpan.dictionary_source (schemas.py).
// Everywhere else that reads evidence_tier (the results table/card chip,
// WordDetail) keeps treating HSK/CC-CEDICT as one undifferentiated
// "Dictionary" tier - this is a new, additive scale for the one place that
// wanted the split, not a replacement for the 4-tier one above.
export type SourceDetailTier = 'user' | 'hsk' | 'cedict' | 'corpus' | 'none';

export function sourceDetailLabel(tier: SourceDetailTier): string {
    const labels: Record<SourceDetailTier, string> = {
        user: 'Your word',
        hsk: 'HSK',
        cedict: 'CC-CEDICT',
        corpus: 'Corpus',
        none: 'None',
    };
    return labels[tier];
}

export function sourceDetailColor(tier: SourceDetailTier): string {
    const colors: Record<SourceDetailTier, string> = {
        // Same indigo as evidenceTierColor's 'user' - same meaning, same
        // color, just present on a finer scale.
        user: 'bg-indigo-100 text-indigo-700',
        // Same blue as evidenceTierColor's 'dictionary' - HSK is the more
        // curated/pedagogical of the two dictionary sources, so it keeps
        // that scale's existing "real dictionary word" color.
        hsk: 'bg-blue-100 text-blue-700',
        // A new hue for the other dictionary source - originally cyan, but
        // that sits right next to Corpus's teal on the color wheel and the
        // two read as nearly the same color in practice. Fuchsia is far
        // enough from HSK's blue, User's indigo, and Corpus's teal to read
        // as a clearly separate fourth color, not used by any other scale
        // in this file.
        cedict: 'bg-fuchsia-100 text-fuchsia-700',
        // Same teal as evidenceTierColor's 'corpus'.
        corpus: 'bg-teal-100 text-teal-700',
        none: 'bg-gray-100 text-gray-600',
    };
    return colors[tier];
}

// Shared rarity label/color mapping - moved here from WordDetailPanel.svelte
// for the same reason (the reading view's "Color by: Rarity" reuses this
// exact scale rather than a third copy).
export function rarityLabel(tier: string | null | undefined): string {
    if (!tier) return 'No data';
    const labels: Record<string, string> = {
        extremely_rare: 'Extremely rare',
        rare: 'Rare',
        uncommon: 'Moderate',
        common: 'Common',
        extremely_common: 'Extremely common',
    };
    return labels[tier] ?? tier;
}

// Each tier's color is the *continuous* rarity gradient (see
// rarityContinuousColor below) evaluated at that tier's own boundary
// frequency, not 5 independently hand-picked colors - this scale's first
// two versions (a single rose ramp, then a grayscale-then-hue-jump scheme)
// both had to guess a shade for each of the 5 steps, and "Moderate" kept
// landing looking louder than intended either way. Sampling the gradient
// itself instead removes the guessing: each color is exactly where that
// tier's own cutoff actually sits on the same log-frequency scale
// compute_word_rarity.py's tiers are built from, so the *spacing* between
// colors reflects the real, uneven spacing between the cutoffs (uncommon's
// range - 1 to 50 occurrences/million - covers much more log-distance than
// rare's - 0.03 to 1 - so their colors end up correspondingly further
// apart) rather than 5 arbitrary, evenly-stepped swatches.
//
// One point per tier, walking from the common end to the rare end:
//   extremely_common: the actual highest freq_per_million in
//     dictionary_words (101202.78, as of the last compute_word_rarity.py
//     run) - "the beginning of the range," i.e. as common as real data
//     ever gets, not just the >= 2250 cutoff that defines the tier (that
//     cutoff is reused below, for `common`, and sampling the gradient
//     there instead would collapse both tiers to the same white - the
//     gradient's own domain (RARITY_LOG_MIN/MAX below) stops exactly at
//     the tier cutoffs, so anything at or beyond 2250 is already "as white
//     as this gradient goes").
//   common: 2250 (the extremely_common/common cutoff)
//   uncommon: 50 (the common/uncommon cutoff)
//   rare: 1 (the uncommon/rare cutoff)
//   extremely_rare: 0.03 (the rare/extremely_rare cutoff - also
//     RARITY_LOG_MIN itself, so this is the gradient's own reddest point)
// Computed once (not derived at runtime - these are fixed design
// constants, same as the tier cutoffs themselves) via the exact
// interpolation rarityContinuousColor below performs, over a domain
// widened on the common end from 2250 to 101202.78 for exactly the reason
// above; the values are hardcoded as arbitrary Tailwind colors since they
// don't land on named shades. One deliberate departure from the computed
// value: extremely_common (see its own comment below).
export function rarityColor(tier: string | null | undefined): string {
    if (!tier) return 'bg-gray-100 text-gray-500';
    const colors: Record<string, string> = {
        // Not literal white - the gradient's own t=0 color is, but a pure
        // white chip is invisible against this app's white cards/table rows
        // (nothing to tell it apart from "no chip here at all"). A light
        // gray keeps the "barely registers" intent while still reading as
        // an actual pill.
        extremely_common: 'bg-gray-100 text-gray-400',
        common: 'bg-[rgb(253,233,165)] text-yellow-700',
        uncommon: 'bg-[rgb(252,210,78)] text-amber-800',
        rare: 'bg-[rgb(252,186,124)] text-orange-800',
        extremely_rare: 'bg-[rgb(252,165,165)] text-red-900',
    };
    return colors[tier] ?? 'bg-gray-100 text-gray-500';
}

// Continuous counterpart to rarityColor, used only by ReadingView's
// "Color by: Rarity" mode (chips/badges elsewhere keep the discrete
// 5-tier rarityColor above - a bucketed badge with a label like "Rare"
// pairs naturally with a bucketed color, but running text has no label at
// all, so a continuous gradient reads better there and sidesteps the
// "jump between tiers" problem entirely, since there are no tier
// boundaries to jump between).
//
// Returns a real `rgb(...)` value, not a Tailwind class - this interpolates
// from the actual freq_per_million number, which no fixed set of utility
// classes could express, so callers apply it via inline
// `style="background-color: ..."` instead of `class`.
//
// Reuses the exact same log10(occurrences-per-million) cutoffs
// compute_word_rarity.py's tier boundaries are built from (0.03 and 2250 -
// see that script's docstring) as the two ends of the gradient, so this
// spans exactly the same range the discrete scale does, just without
// snapping to 5 buckets along the way. Three stops, not two straight from
// white to red - a pure 2-stop gradient spends most of its visible range on
// the common half (word frequency is heavily Zipf-skewed, so most words in
// real text sit on the common side of this range), leaving too little
// visual room for the rare tail to separate itself; the middle amber stop
// keeps rarer-than-average words readably distinct from both ends instead
// of the whole non-extreme range reading as "faintly on its way to red."
const RARITY_LOG_MIN = Math.log10(0.03);
const RARITY_LOG_MAX = Math.log10(2250);
// [common, mid, rare] - amber-300/red-300, capped at the same shade
// ceiling the discrete scale uses, for the same reason: this is a
// background tint behind Chinese text that always stays black (see
// ReadingView's bgOnly()), so going darker would hurt legibility for
// exactly the words this is meant to make easier to spot.
const RARITY_GRADIENT_STOPS: [number, number, number][] = [
    [255, 255, 255], // white - as common as this scale goes
    [252, 211, 77], // amber-300
    [252, 165, 165], // red-300 - as rare as this scale goes
];

export function rarityContinuousColor(freqPerMillion: number | null | undefined): string {
    // No corpus data at all (word isn't in the frequency-scored dictionary)
    // - same neutral gray-100 fallback rarityColor uses for a null tier,
    // not an assumed extreme in either direction.
    if (freqPerMillion == null || freqPerMillion <= 0) return 'rgb(243, 244, 246)';

    const t = Math.min(
        1,
        Math.max(0, (Math.log10(freqPerMillion) - RARITY_LOG_MIN) / (RARITY_LOG_MAX - RARITY_LOG_MIN))
    );
    const rarity = 1 - t; // 0 = as common as it gets, 1 = as rare as it gets

    const segment = rarity <= 0.5 ? 0 : 1;
    const localT = rarity <= 0.5 ? rarity / 0.5 : (rarity - 0.5) / 0.5;
    const [r1, g1, b1] = RARITY_GRADIENT_STOPS[segment];
    const [r2, g2, b2] = RARITY_GRADIENT_STOPS[segment + 1];
    const r = Math.round(r1 + (r2 - r1) * localT);
    const g = Math.round(g1 + (g2 - g1) * localT);
    const b = Math.round(b1 + (b2 - b1) * localT);
    return `rgb(${r}, ${g}, ${b})`;
}
