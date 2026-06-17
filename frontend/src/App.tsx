import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import AdminPage from "./pages/AdminPage";
import DirectoryPage from "./pages/DirectoryPage";
import IngredientDetailPage from "./pages/IngredientDetailPage";
import ProductDetailPage from "./pages/ProductDetailPage";
import ScannerPage from "./pages/ScannerPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<ScannerPage />} />
        <Route path="/directory" element={<DirectoryPage />} />
        <Route path="/admin" element={<Navigate to="/admin/products" replace />} />
        <Route path="/admin/:tab" element={<AdminPage />} />
        <Route path="/database" element={<Navigate to="/admin/products" replace />} />
        <Route path="/status" element={<Navigate to="/admin/imports" replace />} />
        <Route path="/products/:productCode" element={<ProductDetailPage />} />
        <Route path="/ingredients/:ingredientCode" element={<IngredientDetailPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
