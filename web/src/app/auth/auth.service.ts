import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, signal } from '@angular/core';
import { Observable, catchError, finalize, map, of, shareReplay, switchMap, tap, throwError } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthenticatedUser, TokenResponse } from './auth.models';

interface CsrfResponse {
  csrfToken: string;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly authUrl = `${environment.apiBaseUrl}/auth`;
  private accessToken: string | null = null;
  private refreshInFlight?: Observable<string>;

  readonly user = signal<AuthenticatedUser | null>(null);

  constructor(private readonly http: HttpClient) {}

  initialize(): Observable<void> {
    return this.refreshAccessToken().pipe(
      switchMap(() => this.http.get<AuthenticatedUser>(`${this.authUrl}/me/`)),
      tap((user) => this.user.set(user)),
      map(() => undefined),
      catchError((error: unknown) => {
        if (this.isUnauthenticated(error)) {
          this.clearSession();
          return of(undefined);
        }
        return throwError(() => error);
      }),
    );
  }

  login(credentials: LoginCredentials): Observable<AuthenticatedUser> {
    return this.loadCsrfToken().pipe(
      switchMap((csrfToken) =>
        this.http.post<TokenResponse>(
          `${this.authUrl}/login/`,
          { ...credentials, token_transport: 'cookie' },
          { headers: this.csrfHeaders(csrfToken), withCredentials: true },
        ),
      ),
      tap((response) => {
        this.accessToken = response.access;
        this.user.set(response.user ?? null);
      }),
      switchMap((response) =>
        response.user
          ? of(response.user)
          : this.http.get<AuthenticatedUser>(`${this.authUrl}/me/`).pipe(
              tap((user) => this.user.set(user)),
            ),
      ),
    );
  }

  refreshAccessToken(): Observable<string> {
    if (this.refreshInFlight) {
      return this.refreshInFlight;
    }

    this.refreshInFlight = this.loadCsrfToken().pipe(
      switchMap((csrfToken) =>
        this.http.post<TokenResponse>(
          `${this.authUrl}/refresh/`,
          { token_transport: 'cookie' },
          { headers: this.csrfHeaders(csrfToken), withCredentials: true },
        ),
      ),
      map((response) => response.access),
      tap((token) => {
        this.accessToken = token;
      }),
      finalize(() => {
        this.refreshInFlight = undefined;
      }),
      shareReplay({ bufferSize: 1, refCount: false }),
    );
    return this.refreshInFlight;
  }

  logout(): Observable<void> {
    return this.loadCsrfToken().pipe(
      switchMap((csrfToken) =>
        this.http.post<void>(
          `${this.authUrl}/logout/`,
          { token_transport: 'cookie' },
          {
            headers: this.csrfHeaders(csrfToken),
            withCredentials: true,
          },
        ),
      ),
      tap(() => this.clearSession()),
    );
  }

  getAccessToken(): string | null {
    return this.accessToken;
  }

  clearSession(): void {
    this.accessToken = null;
    this.user.set(null);
  }

  private loadCsrfToken(): Observable<string> {
    return this.http
      .get<CsrfResponse>(`${this.authUrl}/csrf/`, { withCredentials: true })
      .pipe(map((response) => response.csrfToken));
  }

  private csrfHeaders(token: string): HttpHeaders {
    return new HttpHeaders({ 'X-CSRFToken': token });
  }

  private isUnauthenticated(error: unknown): boolean {
    return (
      typeof error === 'object' &&
      error !== null &&
      'status' in error &&
      (error.status === 400 || error.status === 401)
    );
  }
}
