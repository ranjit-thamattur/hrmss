# Hotel Vivek – frontend client folder (tenant HV)

Names, sign-in texts, languages (Tamil, English, Hindi) and theme for the hrms-core React app (decision 0006).

- `tenant.js` – texts and languages · `theme.css` – colour overrides
- `npm run dev` – runs the core app with this folder (run `npm install` once in `../hrms-core/frontend`)
- `npm run build` – builds into `../hrms-core/frontend/dist`
- `Dockerfile` – web image (build context: `services/`). Build QA/production images with `--build-arg VITE_HIDE_DEMO_HINT=true`.
