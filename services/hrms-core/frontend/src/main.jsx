import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { AppProvider } from './lib.jsx';
import tenant from '@tenant/tenant.js';
import './styles.css';
import '@tenant/theme.css';

document.title = tenant.name === tenant.product ? tenant.product : `${tenant.product} · ${tenant.name}`;

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AppProvider>
      <App />
    </AppProvider>
  </StrictMode>,
);
