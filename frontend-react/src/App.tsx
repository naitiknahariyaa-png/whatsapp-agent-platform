import React from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { Box, Typography } from "@mui/material";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Alerts from "./pages/Alerts";
import Approvals from "./pages/Approvals";

export default function App() {
  const { token } = useAuth();

  if (!token) {
    return <Login />;
  }

  return (
    <Layout>
      <Box sx={{ p: 3 }}>
        <Typography variant="h5" gutterBottom>
          WhatsApp Agent Platform — Control
        </Typography>
        <Routes>
          <Route path="/" element={<Navigate to="/alerts" replace />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="*" element={<Navigate to="/alerts" replace />} />
        </Routes>
      </Box>
    </Layout>
  );
}