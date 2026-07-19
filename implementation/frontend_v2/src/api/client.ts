export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = 8000): Promise<Response> {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    return response;
  } finally {
    clearTimeout(id);
  }
}

/** Mot so endpoint (7 cai: /api/errors, /api/infra, /api/system/state, ...) boc
 * provenance envelope {data, source, fetched_at}. Unwrap tap trung o day de
 * moi page doc field truc tiep - endpoint tra raw thi giu nguyen. */
function unwrapEnvelope(json: any): any {
  if (json && typeof json === 'object'
      && 'data' in json && 'source' in json && 'fetched_at' in json) {
    return json.data;
  }
  return json;
}

export async function apiGet<T>(path: string): Promise<T> {
  try {
    const response = await fetchWithTimeout(path);
    if (!response.ok) {
      throw new ApiError(`GET ${path} failed: ${response.statusText}`, response.status);
    }
    return unwrapEnvelope(await response.json()) as T;
  } catch (error) {
    console.error(`API GET error on ${path}:`, error);
    throw error;
  }
}

export async function apiPost<T, B = any>(path: string, body?: B): Promise<T> {
  try {
    const response = await fetchWithTimeout(path, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      throw new ApiError(`POST ${path} failed: ${response.statusText}`, response.status);
    }
    return unwrapEnvelope(await response.json()) as T;
  } catch (error) {
    console.error(`API POST error on ${path}:`, error);
    throw error;
  }
}

export function getMediaUrl(path?: string): string {
  if (!path) return '';
  let clean = path.replace(/\\/g, '/');
  if (clean.startsWith('/media/')) return clean;
  if (clean.startsWith('media/')) return '/' + clean;
  const idx = clean.indexOf('/output/');
  if (idx !== -1) {
    return '/media/' + clean.slice(idx + 8);
  }
  return '/media/' + clean;
}
