import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { environment } from '../../environments/environment';
import { authInterceptor } from './auth.interceptor';
import { AuthService } from './auth.service';

describe('AuthService', () => {
  let auth: AuthService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    auth = TestBed.inject(AuthService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('uses the CSRF-protected cookie login and keeps the access token in memory', () => {
    const user = {
      id: 'user-id',
      email: 'farmer@example.test',
      first_name: 'Ada',
      last_name: 'Farmer',
      roles: ['farmer' as const],
    };
    let completed = false;

    auth.login({ email: user.email, password: 'not-stored' }).subscribe((result) => {
      expect(result).toEqual(user);
      completed = true;
    });

    const csrf = http.expectOne('http://localhost:8000/api/v1/auth/csrf/');
    expect(csrf.request.withCredentials).toBe(true);
    csrf.flush({ csrfToken: 'csrf-value' });

    const login = http.expectOne('http://localhost:8000/api/v1/auth/login/');
    expect(login.request.withCredentials).toBe(true);
    expect(login.request.headers.get('X-CSRFToken')).toBe('csrf-value');
    expect(login.request.body).toEqual({
      email: user.email,
      password: 'not-stored',
      token_transport: 'cookie',
    });
    login.flush({ access: 'short-lived-access-token', user });

    expect(completed).toBe(true);
    expect(auth.getAccessToken()).toBe('short-lived-access-token');
    expect(auth.user()).toEqual(user);

    let responseReceived = false;
    TestBed.inject(HttpClient)
      .get(`${environment.apiBaseUrl}/orders/`)
      .subscribe(() => (responseReceived = true));
    const orders = http.expectOne(`${environment.apiBaseUrl}/orders/`);
    expect(orders.request.headers.get('Authorization')).toBe('Bearer short-lived-access-token');
    expect(orders.request.withCredentials).toBe(true);
    orders.flush({ results: [] });
    expect(responseReceived).toBe(true);
  });

  it('refreshes through the HttpOnly cookie without sending a refresh token in JSON', () => {
    auth.login({ email: 'farmer@example.test', password: 'not-stored' }).subscribe();
    const loginCsrf = http.expectOne('http://localhost:8000/api/v1/auth/csrf/');
    loginCsrf.flush({ csrfToken: 'login-csrf' });
    const login = http.expectOne('http://localhost:8000/api/v1/auth/login/');
    login.flush({
      access: 'expired-access-token',
      user: {
        id: 'user-id',
        email: 'farmer@example.test',
        first_name: 'Ada',
        last_name: 'Farmer',
        roles: ['farmer'],
      },
    });

    let accessToken = '';
    auth.refreshAccessToken().subscribe((token) => (accessToken = token));

    const csrf = http.expectOne('http://localhost:8000/api/v1/auth/csrf/');
    expect(csrf.request.headers.has('Authorization')).toBe(false);
    csrf.flush({ csrfToken: 'csrf-value' });

    const refresh = http.expectOne('http://localhost:8000/api/v1/auth/refresh/');
    expect(refresh.request.withCredentials).toBe(true);
    expect(refresh.request.headers.get('X-CSRFToken')).toBe('csrf-value');
    expect(refresh.request.headers.has('Authorization')).toBe(false);
    expect(refresh.request.body).toEqual({ token_transport: 'cookie' });
    refresh.flush({ access: 'rotated-access-token' });

    expect(accessToken).toBe('rotated-access-token');
    expect(auth.getAccessToken()).toBe('rotated-access-token');
  });
});
