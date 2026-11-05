import { inject } from '@angular/core';
import { ActivatedRouteSnapshot, CanActivateFn, Router } from '@angular/router';
import { AuthService } from './auth.service';
import { UserRole } from './auth.models';

export const authGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  return auth.user() ? true : inject(Router).createUrlTree(['/login']);
};

export const profileGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const roles = auth.user()?.roles ?? [];
  return roles.includes('farmer') || roles.includes('buyer')
    ? true
    : inject(Router).createUrlTree(['/']);
};

export const roleGuard: CanActivateFn = (route: ActivatedRouteSnapshot) => {
  const roles = inject(AuthService).user()?.roles ?? [];
  const allowed = route.data['roles'] as UserRole[] | undefined;
  return allowed?.some((role) => roles.includes(role))
    ? true
    : inject(Router).createUrlTree(['/']);
};
