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

// Shared source label/color mapping - moved here from the results page so
// the reading view (ReadingView.svelte) can reuse the exact same "Color
// by: Source" scale instead of a third copy of this lookup table.
export function sourceLabel(source: string | null | undefined): string {
    if (!source) return 'unknown';
    const labels: Record<string, string> = {
        dag: 'segmenter',
        overlay: 'your word',
        token: 'unknown seq.',
        unknown: 'unknown',
        longest_match_only: 'extra match',
        trie: 'segmenter', // legacy label from before the DAG segmenter
    };
    return labels[source] ?? source;
}

export function sourceColor(source: string | null | undefined): string {
    if (!source) return 'bg-gray-100 text-gray-600';
    const colors: Record<string, string> = {
        dag: 'bg-blue-100 text-blue-700',
        trie: 'bg-blue-100 text-blue-700',
        overlay: 'bg-indigo-100 text-indigo-700',
        token: 'bg-purple-100 text-purple-700',
        unknown: 'bg-gray-100 text-gray-600',
        longest_match_only: 'bg-amber-100 text-amber-700',
    };
    return colors[source] ?? 'bg-gray-100 text-gray-600';
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
