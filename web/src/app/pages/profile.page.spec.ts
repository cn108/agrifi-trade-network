import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { AuthService } from '../auth/auth.service';
import { authInterceptor } from '../auth/auth.interceptor';
import { environment } from '../../environments/environment';
import { ProfilePage } from './profile.page';

describe('ProfilePage', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [ProfilePage],
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
      ],
    });
    TestBed.inject(AuthService).user.set({
      id: 'buyer-id',
      email: 'buyer@example.test',
      first_name: 'Ada',
      last_name: 'Buyer',
      roles: ['buyer'],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('loads the caller profile and never submits role or verification fields', () => {
    const fixture = TestBed.createComponent(ProfilePage);
    fixture.detectChanges();

    http.expectOne(`${environment.apiBaseUrl}/auth/me/`).flush({
      id: 'buyer-id',
      email: 'buyer@example.test',
      first_name: 'Ada',
      last_name: 'Buyer',
      roles: ['buyer'],
    });
    http.expectOne(`${environment.apiBaseUrl}/auth/profiles/buyer/`).flush({
      id: 'profile-id',
      business_name: 'Northern Produce Ltd',
      region: 'Kaduna',
      location: 'Zaria',
      verification_status: 'pending',
    });

    const page = fixture.componentInstance;
    expect(page.verificationStatus()).toBe('pending');
    page.profileForm.patchValue({
      name: 'Northern Produce Group',
      region: 'Kano',
      location: 'Kano City',
    });
    page.saveProfile();

    const profilePatch = http.expectOne(`${environment.apiBaseUrl}/auth/profiles/buyer/`);
    expect(profilePatch.request.method).toBe('PATCH');
    expect(profilePatch.request.body).toEqual({
      business_name: 'Northern Produce Group',
      region: 'Kano',
      location: 'Kano City',
    });
    profilePatch.flush({
      id: 'profile-id',
      business_name: 'Northern Produce Group',
      region: 'Kano',
      location: 'Kano City',
      verification_status: 'pending',
    });

    page.accountForm.patchValue({ first_name: 'Ada', last_name: 'Nwosu' });
    page.saveAccount();
    const accountPatch = http.expectOne(`${environment.apiBaseUrl}/auth/me/`);
    expect(accountPatch.request.body).toEqual({ first_name: 'Ada', last_name: 'Nwosu' });
    accountPatch.flush({
      id: 'buyer-id',
      email: 'buyer@example.test',
      first_name: 'Ada',
      last_name: 'Nwosu',
      roles: ['buyer'],
    });

    expect(page.profileMessage()).toBe('Profile saved. Verification status is unchanged.');
    expect(page.accountMessage()).toBe('Personal details saved.');
    expect(page.verificationStatus()).toBe('pending');
  });
});
