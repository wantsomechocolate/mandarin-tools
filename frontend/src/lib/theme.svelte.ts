import { browser } from '$app/environment';

const STORAGE_KEY = 'mandarin_tools_theme';

// Three states, not two: 'system' (the default - no stored preference,
// follow prefers-color-scheme live) vs an explicit 'light'/'dark' override
// that wins regardless of OS setting. Only 'light'/'dark' are ever written
// to storage - 'system' is represented by the KEY BEING ABSENT, not a
// stored 'system' string, so a user can get back to "just follow the OS"
// by clearing their choice, and so this module and the inline theme
// script in app.html (which can't import this file, and has to
// special-case the same "system" fallback by hand) agree on what an
// empty/missing localStorage value means.
export type ThemePreference = 'system' | 'light' | 'dark';

function loadStoredPreference(): ThemePreference {
	if (!browser) return 'system';
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		return raw === 'light' || raw === 'dark' ? raw : 'system';
	} catch {
		return 'system';
	}
}

// Module-level $state - this file is the one place in the app that needs
// genuinely reactive theme info in JS, not just a CSS `dark:` variant:
// ReadingView.svelte's rarity gradient is an interpolated inline
// background-color, computed in script, not a fixed Tailwind class, so it
// has nothing to react to a `dark` class the way `dark:` utilities do -
// it needs to be told directly. Everywhere else in the app just uses
// `dark:` classes against the `<html>` element's own class (set by
// applyClass below), with no need to import this module at all.
let preference = $state<ThemePreference>(loadStoredPreference());
let systemPrefersDark = $state(browser && window.matchMedia('(prefers-color-scheme: dark)').matches);

function applyClass(): void {
	if (!browser) return;
	document.documentElement.classList.toggle('dark', isDarkMode());
}

if (browser) {
	// Live-updates 'system' users if their OS theme changes while the app
	// is open (e.g. a scheduled light/dark switch, or the user changing it
	// in their OS settings) - an explicit 'light'/'dark' choice is
	// unaffected, since isDarkMode() only consults systemPrefersDark when
	// preference is 'system'.
	window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
		systemPrefersDark = e.matches;
		applyClass();
	});
}
// Reconciles with the inline script in app.html, which already set the
// class before first paint from the same stored value - this is normally
// a no-op, cheap enough not to bother skipping.
applyClass();

export function getThemePreference(): ThemePreference {
	return preference;
}

// Reactive read - call from a template expression or $derived/$effect to
// track it. See ReadingView.svelte's spanStyle() for the one real
// consumer.
export function isDarkMode(): boolean {
	return preference === 'dark' || (preference === 'system' && systemPrefersDark);
}

export function setThemePreference(next: ThemePreference): void {
	preference = next;
	if (browser) {
		try {
			if (next === 'system') localStorage.removeItem(STORAGE_KEY);
			else localStorage.setItem(STORAGE_KEY, next);
		} catch {
			// e.g. storage disabled/full - the choice still applies for this
			// session (preference itself already updated above), just won't
			// survive a reload.
		}
	}
	applyClass();
}
