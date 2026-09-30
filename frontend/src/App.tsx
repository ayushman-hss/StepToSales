import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { restoreSession } from './api';
import { Layout } from './components/Layout';
import { RequireAuth } from './components/RequireAuth';
import { LandingPage } from './pages/LandingPage';
import { LoginPage } from './pages/LoginPage';
import { DashboardPage } from './pages/DashboardPage';
import { ProductsPage } from './pages/ProductsPage';
import { BundlesPage } from './pages/BundlePage';
import { PoolsPage } from './pages/PoolsPage';
import { TillPage } from './pages/TillPage';

export default function App() {
  // A token saved from an earlier visit is only trusted once the server
  // confirms it; until then protected pages show "checking".
  useEffect(() => {
    restoreSession();
  }, []);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Layout />}>
        <Route path="/" element={<LandingPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/products" element={<ProductsPage />} />
          <Route path="/bundles" element={<BundlesPage />} />
          <Route path="/pools" element={<PoolsPage />} />
          <Route path="/pos" element={<TillPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
