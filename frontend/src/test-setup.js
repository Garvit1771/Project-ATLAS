// ATLAS — Vitest test setup
// Extends Vitest's expect with jest-dom matchers.
// This file is loaded before every test via vite.config.js setupFiles.
import '@testing-library/jest-dom'

// jsdom does not implement scrollIntoView — stub it so components that call
// ref.scrollIntoView({ behavior: 'smooth' }) do not throw in tests.
window.HTMLElement.prototype.scrollIntoView = function () {}
