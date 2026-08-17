<script lang="ts">
	import * as api from '$lib/api';
	import { setToken, isLoggedIn } from '$lib/auth';
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	let email = $state('');
	let password = $state('');
	let error = $state('');
	let loading = $state(false);

	onMount(() => {
		if (isLoggedIn()) goto('/');
	});

	async function handleSubmit() {
		error = '';
		loading = true;
		try {
			const token = await api.login(email, password);
			setToken(token);
			goto('/');
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Login failed';
		} finally {
			loading = false;
		}
	}
</script>

<div class="min-h-screen bg-gray-50 flex items-center justify-center">
	<div class="bg-white p-8 rounded-lg shadow-md w-full max-w-md">
		<h1 class="text-2xl font-bold text-gray-800 mb-6">Sign in to Mandarin Tools</h1>

		{#if error}
			<div class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
				{error}
			</div>
		{/if}

		<div class="space-y-4">
			<div>
				<label class="block text-sm font-medium text-gray-700 mb-1" for="email">Email</label>
				<input
					id="email"
					type="email"
					bind:value={email}
					class="w-full border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
					placeholder="you@example.com"
				/>
			</div>

			<div>
				<label class="block text-sm font-medium text-gray-700 mb-1" for="password">Password</label>
				<input
					id="password"
					type="password"
					bind:value={password}
					class="w-full border border-gray-300 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
					placeholder="••••••••"
				/>
			</div>

			<button
				onclick={handleSubmit}
				disabled={loading}
				class="w-full bg-blue-600 text-white py-2 px-4 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed font-medium"
			>
				{loading ? 'Signing in...' : 'Sign in'}
			</button>
		</div>

		<p class="mt-4 text-sm text-gray-600 text-center">
			Don't have an account?
			<a href="/register" class="text-blue-600 hover:underline">Register</a>
		</p>
	</div>
</div>