import { getToken } from './auth';

// Derived from whatever host the page was actually loaded from (not
// hardcoded to localhost) so this keeps working when the frontend is
// reached over the LAN (e.g. `npm run dev -- --host 0.0.0.0`, opened from a
// phone as http://<lan-ip>:5173) - the API calls then correctly target that
// same host on port 8000 instead of the phone's own "localhost". Falls back
// to localhost when `window` isn't available (e.g. during SSR, though this
// app currently runs with SSR disabled).
const BASE_URL = typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : 'http://localhost:8000';

// Scoping (user words): "global" (default, unchanged from before scoping
// existed) applies everywhere; "text" scopes to every analysis of one input
// text; "analysis" scopes to just one analysis run. See the backend's
// ScopeChoice (schemas.py) and UserWord's scope_analysis_id/
// scope_input_text_id docstring (models.py).
export type Scope = 'global' | 'text' | 'analysis';

export interface ScopeContext {
    analysisId?: number;
    inputTextId?: number;
    scope?: Scope;
}

// Builds the "?analysis_id=..&input_text_id=.." query string used by the
// resolved-view list/detail GET endpoints - omits a param entirely when
// undefined, since the backend treats "not provided" and "provided as
// null" differently (see router.py's _scope_filter_conditions).
function viewingContextQuery(analysisId?: number, inputTextId?: number): string {
    const params = new URLSearchParams();
    if (analysisId !== undefined) params.set('analysis_id', String(analysisId));
    if (inputTextId !== undefined) params.set('input_text_id', String(inputTextId));
    const qs = params.toString();
    return qs ? `?${qs}` : '';
}

// Builds the "?scope_analysis_id=..&scope_input_text_id=.." query string
// used by DELETE endpoints to target exactly one scoped row.
function exactScopeQuery(scopeAnalysisId?: number | null, scopeInputTextId?: number | null): string {
    const params = new URLSearchParams();
    if (scopeAnalysisId != null) params.set('scope_analysis_id', String(scopeAnalysisId));
    if (scopeInputTextId != null) params.set('scope_input_text_id', String(scopeInputTextId));
    const qs = params.toString();
    return qs ? `?${qs}` : '';
}

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

// Re-runs analysis against an existing input text (a new Analysis is
// created under it, distinct from any earlier runs of the same text).
export async function reanalyzeInputText(inputTextId: number) {
    return request('POST', '/known-words/analyze', { input_text_id: inputTextId });
}

export async function getAnalysis(id: number) {
    return request('GET', `/known-words/analyze/${id}`);
}

// Reading-view payload (ReadingView.svelte) - a separate, opt-in-cost
// endpoint from getAnalysis above, which the results table doesn't need
// to pay for. See AnalysisSpan's docstring (schemas.py) for the shape.
export async function getAnalysisSpans(id: number) {
    return request('GET', `/known-words/analyze/${id}/spans`);
}

export async function getWordContext(analysisId: number, word: string) {
    return request('GET', `/known-words/analyze/${analysisId}/context/${encodeURIComponent(word)}`);
}

export async function listInputTexts() {
    return request('GET', '/known-words/input-texts');
}

export async function getInputText(id: number) {
    return request('GET', `/known-words/input-texts/${id}`);
}

export async function deleteInputText(id: number) {
    return request('DELETE', `/known-words/input-texts/${id}`);
}

// Known words - familiarity is always global (see KnownWord's docstring,
// models.py), unlike user words below.
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
// affects_dag is always explicitly sent as true here (never omitted) -
// this is the quick "+ Add word" action (row/card bookmark button, panel's
// own bookmark icon), a deliberate "yes, this is a word, help the segmenter
// recognize it" action, not a bare request that merely mentions other
// fields - see UserWordCreate's docstring (schemas.py) for why the
// server-side default is None ("no opinion"), not true: that default
// exists to protect requests which DON'T express a segmentation opinion,
// not to change what this deliberate action does.
export async function createUserWord(word: string, notes?: string, ctx?: ScopeContext) {
    return request('POST', '/known-words/user-words', {
        word,
        notes,
        affects_dag: true,
        analysis_id: ctx?.analysisId,
        input_text_id: ctx?.inputTextId,
        scope: ctx?.scope ?? 'global',
    });
}

export async function listUserWords(analysisId?: number, inputTextId?: number) {
    return request('GET', `/known-words/user-words${viewingContextQuery(analysisId, inputTextId)}`);
}

// Every UserWord row for the user across every scope, unresolved - each
// annotated with `input_text_title` for text/analysis-scoped rows (see
// list_user_words' all_scopes docstring, router.py). For the profile
// "all your user words" management page - NOT for anything that feeds
// segmentation or a single analysis's viewing context, which both stay on
// the resolved listUserWords(analysisId, inputTextId) above.
export async function listAllUserWords() {
    return request('GET', '/known-words/user-words?all_scopes=true');
}

export async function deleteUserWord(word: string, scopeAnalysisId?: number | null, scopeInputTextId?: number | null) {
    return request(
        'DELETE',
        `/known-words/user-words/${encodeURIComponent(word)}${exactScopeQuery(scopeAnalysisId, scopeInputTextId)}`
    );
}

export async function upsertUserWordDetail(
    word: string,
    fields: { pronunciation?: string | null; meaning?: string | null; notes?: string | null; affects_dag?: boolean | null },
    ctx?: ScopeContext
) {
    return request('PUT', `/known-words/user-words/${encodeURIComponent(word)}`, {
        ...fields,
        analysis_id: ctx?.analysisId,
        input_text_id: ctx?.inputTextId,
        scope: ctx?.scope ?? 'global',
    });
}

// Word visibility ("hide from results") - see WordVisibility's docstring
// (models.py) for why this is its own scoped table, separate from user
// words. Same create-or-update pattern as upsertUserWordDetail, but
// `hidden` is always required and always written (no partial-update
// nuance - see WordVisibilityUpsert, schemas.py).
export async function upsertWordVisibility(word: string, hidden: boolean, ctx?: ScopeContext) {
    return request('PUT', `/known-words/word-visibility/${encodeURIComponent(word)}`, {
        hidden,
        analysis_id: ctx?.analysisId,
        input_text_id: ctx?.inputTextId,
        scope: ctx?.scope ?? 'global',
    });
}

export async function deleteWordVisibility(word: string, scopeAnalysisId?: number | null, scopeInputTextId?: number | null) {
    return request(
        'DELETE',
        `/known-words/word-visibility/${encodeURIComponent(word)}${exactScopeQuery(scopeAnalysisId, scopeInputTextId)}`
    );
}

// Sample sentences - a word can have many, independent of whether it's a
// UserWord (see SampleSentence's docstring, models.py). Global per
// user+word, no scoping.
export async function listSampleSentences(word: string) {
    return request('GET', `/known-words/sample-sentences?word=${encodeURIComponent(word)}`);
}

export async function addSampleSentence(word: string, sentence: string) {
    return request('POST', '/known-words/sample-sentences', { word, sentence });
}

export async function deleteSampleSentence(sentenceId: number) {
    return request('DELETE', `/known-words/sample-sentences/${sentenceId}`);
}

// Starred words — a lightweight personal bookmark, global only (no scoping,
// unlike known/user words - see StarredWord's docstring).
export async function listStarredWords() {
    return request('GET', '/known-words/starred-words');
}

export async function createStarredWord(word: string, note?: string) {
    return request('POST', '/known-words/starred-words', { word, note });
}

export async function deleteStarredWord(word: string) {
    return request('DELETE', `/known-words/starred-words/${encodeURIComponent(word)}`);
}

export async function upsertStarredWord(word: string, note?: string | null) {
    return request('PUT', `/known-words/starred-words/${encodeURIComponent(word)}`, { note });
}

// Stopwords
export async function listStopwords() {
    return request('GET', '/known-words/stopwords');
}

export async function createStopword(word: string, is_override: boolean = false) {
    return request('POST', '/known-words/stopwords', { word, is_override });
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

// Reverses whatever is currently making `word` show as garbage (the user's
// own marking, or a system-default one cancelled out via an override row -
// see unmark_garbage_word's docstring, router.py). Word-based, same calling
// convention as deleteUserWord.
export async function unmarkGarbageWord(word: string) {
    return request('DELETE', `/known-words/garbage-words/word/${encodeURIComponent(word)}`);
}

export async function getWordDetail(word: string, analysisId?: number, inputTextId?: number) {
    return request('GET', `/known-words/words/${encodeURIComponent(word)}${viewingContextQuery(analysisId, inputTextId)}`);
}