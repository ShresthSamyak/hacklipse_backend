# Structured Testimony - Frontend Dashboard

A production-grade React frontend built with Vite, TypeScript, and Tailwind CSS. This project follows a scalable, feature-based architecture (FSD-lite) designed for large-scale applications.

## 🚀 Tech Stack

- **Framework:** React 19 (TypeScript)
- **Build Tool:** Vite 8
- **Styling:** Tailwind CSS 4
- **State Management:** Zustand 5
- **Routing:** React Router 7
- **Code Quality:** ESLint 9 + Prettier

## 🏗️ Architecture

The project follows a modular structure inside `src/`:

- `app/`: Global configuration (providers, router, root layout, global store).
- `features/`: Business-logic modules (e.g., `auth`, `forensics`, `cases`).
- `pages/`: Route-level components.
- `widgets/`: Compositional UI blocks (larger than components, smaller than pages).
- `shared/`: Reusable primitives (UI components, hooks, utilities, types).
- `assets/`: Static media (images, fonts).
- `styles/`: Global CSS and Tailwind directives.
- `config/`: App-wide constants and environment management.

## 🛠️ Getting Started

### Prerequisites

- Node.js (Latest LTS recommended)
- npm or yarn

### Installation

```bash
cd client
npm install
```

### Development

```bash
npm run dev
```

### Production Build

```bash
npm run build
```

### Formatting & Linting

```bash
npm run format # Fix formatting with Prettier
npm run lint   # Run ESLint checks
```

## 📐 Project Structure

```text
src/
├── app/
│   ├── layouts/
│   ├── providers/
│   ├── router/
│   └── store/
├── assets/
├── config/
├── features/
├── pages/
├── shared/
│   ├── components/
│   ├── hooks/
│   ├── utils/
│   └── types/
├── styles/
├── widgets/
└── main.tsx
```

## 🔑 Environment Variables

Copy `.env.example` to `.env` and fill in the values:

```bash
VITE_API_BASE_URL=http://localhost:3000
```
