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
