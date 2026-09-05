import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

import App from './App.jsx';
import './index.css';

/**
 * Entry point.
 *
 * StrictMode is on. It double-invokes effects in development, which is exactly
 * what surfaces the class of bug this page could plausibly have: the API probe
 * in the simulator and the IntersectionObserver in the scroll spy both set up
 * subscriptions, and both must tear down cleanly. If either leaked, StrictMode
 * would make it visible immediately rather than in production.
 */
const container = document.getElementById('root');

if (!container) {
  throw new Error('Root element #root not found in index.html');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
