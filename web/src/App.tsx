import { Navigate, Route, Routes } from "react-router-dom";
import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { Layout } from "./components/Layout";
import { JobDetailPage } from "./pages/JobDetailPage";
import { JobsPage } from "./pages/JobsPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { NewsletterPage } from "./pages/NewsletterPage";

function ScrollToRouteTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

export function App() {
  return (
    <>
      <ScrollToRouteTop />
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<JobsPage />} />
          <Route path="jobs" element={<Navigate replace to="/" />} />
          <Route path="jobs/:jobId" element={<JobDetailPage />} />
          <Route path="newsletter" element={<NewsletterPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </>
  );
}
