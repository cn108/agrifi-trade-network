import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError } from 'rxjs';
import { environment } from '../../environments/environment';
import { AuthService } from './auth.service';

export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (!request.url.startsWith(environment.apiBaseUrl)) {
    return next(request);
  }

  const isCookieAuthEndpoint = /\/auth\/(csrf|login|refresh|register)\//.test(request.url);
  const accessToken = isCookieAuthEndpoint ? null : auth.getAccessToken();
  const withCredentials = request.clone({
    withCredentials: true,
    setHeaders: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });

  return next(withCredentials).pipe(
    catchError((error: unknown) => {
      const isAuthEndpoint = /\/auth\/(csrf|login|refresh|logout)\//.test(request.url);
      if (!(error instanceof HttpErrorResponse) || error.status !== 401 || isAuthEndpoint) {
        return throwError(() => error);
      }

      return auth.refreshAccessToken().pipe(
        switchMap((token) =>
          next(
            request.clone({
              withCredentials: true,
              setHeaders: { Authorization: `Bearer ${token}` },
            }),
          ),
        ),
        catchError((refreshError: unknown) => {
          auth.clearSession();
          void router.navigate(['/login']);
          return throwError(() => refreshError);
        }),
      );
    }),
  );
};
