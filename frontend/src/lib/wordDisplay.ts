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

export function rarityColor(tier: string | null | undefined): string {
    if (!tier) return 'bg-gray-100 text-gray-500';
    const colors: Record<string, string> = {
        extremely_rare: 'bg-gray-100 text-gray-500',
        rare: 'bg-stone-200 text-stone-600',
        uncommon: 'bg-yellow-100 text-yellow-700',
        common: 'bg-orange-100 text-orange-700',
        extremely_common: 'bg-red-100 text-red-700',
    };
    return colors[tier] ?? 'bg-gray-100 text-gray-500';
}
