import { getToken } from './auth';

const BASE_URL = 'http://localhost:8000';

async function request<T>(
    method: string,
    path: string,
    body?: unknown,
): Promise<T> {
    const token = getToken();
    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
    };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${BASE_URL}${path}`, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
    });

    if (response.status === 401) {
        import('./auth').then(({ logout }) => logout());
        throw new Error('Unauthorized');
    }

    if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || `Request failed: ${response.status}`);
    }

    if (response.status === 204) {
        return undefined as T;
    }

    return response.json();
}

// Auth
export async function login(email: string, password: string): Promise<string> {
    const form = new URLSearchParams();
    form.append('username', email);
    form.append('password', password);

    const response = await fetch(`${BASE_URL}/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: form,
    });

    if (!response.ok) {
        throw new Error('Invalid email or password');
    }

    const data = await response.json();
    return data.access_token;
}

export async function register(email: string, username: string, password: string) {
    return request('POST', '/auth/register', { email, username, password });
}

// Analysis
export async function analyzeText(title: string | null, body: string) {
    return request('POST', '/known-words/analyze', { title, body });
}

export async function getAnalysis(id: number) {
    return request('GET', `/known-words/analyze/${id}`);
}

export async function listInputTexts() {
    return request('GET', '/known-words/input-texts');
}

export async function deleteInputText(id: number) {
    return request('DELETE', `/known-words/input-texts/${id}`);
}

// Known words
export async function upsertKnownWord(word: string, familiarity: number | null) {
    return request('POST', '/known-words/known-words', { word, familiarity });
}

export async function listKnownWords() {
    return request('GET', '/known-words/known-words');
}

export async function deleteKnownWord(word: string) {
    return request('DELETE', `/known-words/known-words/${encodeURIComponent(word)}`);
}

// User words
export async function createUserWord(word: string, notes?: string) {
    return request('POST', '/known-words/user-words', { word, notes });
}

export async function listUserWords() {
    return request('GET', '/known-words/user-words');
}

export async function deleteUserWord(word: string) {
    return request('DELETE', `/known-words/user-words/${encodeURIComponent(word)}`);
}

export async function upsertUserWordDetail(
    word: string,
    fields: { pronunciation?: string | null; meaning?: string | null; notes?: string | null }
) {
    return request('PUT', `/known-words/user-words/${encodeURIComponent(word)}`, fields);
}

// Fragments — segmentation artifacts worth annotating but not studying.
// Kept separate from user words: never touches segmentation weighting.
export async function listFragments() {
    return request('GET', '/known-words/fragments');
}

export async function createFragment(word: string, note?: string) {
    return request('POST', '/known-words/fragments', { word, note });
}

export async function deleteFragment(word: string) {
    return request('DELETE', `/known-words/fragments/${encodeURIComponent(word)}`);
}

export async function upsertFragment(word: string, note?: string | null) {
    return request('PUT', `/known-words/fragments/${encodeURIComponent(word)}`, { note });
}

// Stopwords
export async function listStopwords() {
    return request('GET', '/known-words/stopwords');
}

export async function createStopword(word: string, algo_type: string, is_override: boolean = false) {
    return request('POST', '/known-words/stopwords', { word, algo_type, is_override });
}

export async function deleteStopword(id: number) {
    return request('DELETE', `/known-words/stopwords/${id}`);
}

// Garbage words
export async function listGarbageWords() {
    return request('GET', '/known-words/garbage-words');
}

export async function createGarbageWord(word: string, is_override: boolean = false) {
    return request('POST', '/known-words/garbage-words', { word, is_override });
}

export async function deleteGarbageWord(id: number) {
    return request('DELETE', `/known-words/garbage-words/${id}`);
}

export async function getWordDetail(word: string) {
    return request('GET', `/known-words/words/${encodeURIComponent(word)}`);
}