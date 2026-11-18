// Hotel Vivek (tenant code HV): names, texts and languages shown in the app (decision 0006).
// Used by hrms-core/frontend through the @tenant alias; nothing here is shared with other clients.
export default {
  code: 'HV',
  name: 'Hotel Vivek',
  product: 'Peak HRMS',
  loginHeadline: 'Hotel Vivek HR: people, attendance and payroll for 3 entities and 5 locations.',
  loginText: 'Employee records, biometric attendance, payroll with HR and Finance approval, statutory files, exits and self-service.',
  // Shown on the sign-in page for laptop builds only. QA/production images are built with VITE_HIDE_DEMO_HINT=true.
  demoHint: import.meta.env.VITE_HIDE_DEMO_HINT === 'true' ? ''
    : 'Demo users (synthetic, laptops only): admin@, hr@, payroll@, finance@, hod@, employee@hotelvivek.local · password Peak@12345',
  languages: [{ code: 'ta', label: 'Tamil' }, { code: 'en', label: 'English' }, { code: 'hi', label: 'Hindi' }],
  defaultLanguage: 'ta',
};
