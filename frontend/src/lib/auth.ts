import { browser } from '$app/environment';
import { goto } from '$app/navigation';

const TOKEN_KEY = 'mandarin_tools_token';

export function getToken(): string | null {
    if (!browser) return null;
    return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
    if (!browser) return;
    localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
    if (!browser) return;
    localStorage.removeItem(TOKEN_KEY);
}

export function isLoggedIn(): boolean {
    return getToken() !== null;
}

export function logout(): void {
    clearToken();
    goto('/login');
}