<script lang="ts">
	import { onMount } from 'svelte';
	import { isLoggedIn, logout } from '$lib/auth';
	import * as api from '$lib/api';
	import { goto } from '$app/navigation';

	let inputTexts: any[] = $state([]);
	let loading = $state(true);
	let error = $state('');

	onMount(async () => {
		if (!isLoggedIn()) {
			goto('/login');
			return;
		}
		try {
			inputTexts = await api.listInputTexts() as any[];
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to load texts';
		} finally {
			loading = false;
		}
	});

	async function handleDelete(id: number) {
		if (!confirm('Delete this text?')) return;
		try {
			await api.deleteInputText(id);
			inputTexts = inputTexts.filter((t) => t.id !== id);
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Failed to delete';
		}
	}
</script>

<div class="min-h-screen bg-gray-50">
	<nav class="bg-white shadow-sm px-6 py-4 flex justify-between items-center">
		<h1 class="text-xl font-bold text-gray-800">Mandarin Tools</h1>
		<div class="flex gap-4">
			<a href="/analyze" class="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 text-sm font-medium">
				New Analysis
			</a>
			<button
				onclick={logout}
				class="text-gray-600 hover:text-gray-800 text-sm font-medium"
			>
				Sign out
			</button>
		</div>
	</nav>

	<main class="max-w-4xl mx-auto px-6 py-8">
		<h2 class="text-2xl font-bold text-gray-800 mb-6">Your Texts</h2>

		{#if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
				{error}
			</div>
		{/if}

		{#if loading}
			<p class="text-gray-500">Loading...</p>
		{:else if inputTexts.length === 0}
			<div class="text-center py-16 text-gray-500">
				<p class="text-lg mb-4">No texts yet.</p>
				<a href="/analyze" class="bg-blue-600 text-white px-6 py-3 rounded-md hover:bg-blue-700 font-medium">
					Analyze your first text
				</a>
			</div>
		{:else}
			<div class="space-y-3">
				{#each inputTexts as text}
					<div class="bg-white rounded-lg shadow-sm p-4 flex justify-between items-center">
						<div>
							<a
							href="/input-texts/{text.id}"
							    class="font-medium text-blue-600 hover:underline"
							>
							    {text.title ?? 'Untitled'}
							</a>
							<p class="text-sm text-gray-500 mt-1">
								{new Date(text.created_at).toLocaleDateString()}
							</p>
						</div>
						<div class="flex items-center gap-4">
							{#if text.latest_analysis_id}
								<a
									href="/analyze/{text.latest_analysis_id}"
									class="text-sm text-blue-600 hover:underline"
								>
									View latest results →
								</a>
							{/if}
							<button
								onclick={() => handleDelete(text.id)}
								class="text-red-500 hover:text-red-700 text-sm"
							>
								Delete
							</button>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</main>
</div>