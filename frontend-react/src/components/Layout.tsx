import React from "react";
import { AppBar, Toolbar, Typography, IconButton, Box, Tabs, Tab, Link } from "@mui/material";
import LogoutIcon from "@mui/icons-material/Logout";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth";

export default function Layout({ children }: { children: React.ReactNode }) {
  const { logout, email } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const tab = loc.pathname.startsWith("/approvals") ? "/approvals" : "/alerts";

  return (
    <>
      <AppBar position="static">
        <Toolbar>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            WA Agent Control
          </Typography>
          {email && (
            <Typography variant="caption" sx={{ mr: 2 }}>
              {email}
            </Typography>
          )}
          <IconButton color="inherit" onClick={() => { logout(); nav("/"); }} aria-label="logout">
            <LogoutIcon />
          </IconButton>
        </Toolbar>
      </AppBar>
      <Box sx={{ borderBottom: 1, borderColor: "divider" }}>
        <Tabs value={tab} onChange={(_, v) => nav(v)}>
          <Tab label="Alerts" value="/alerts" />
          <Tab label="Approvals" value="/approvals" />
        </Tabs>
      </Box>
      <Box component="main" sx={{ p: 2 }}>
        {children}
      </Box>
    </>
  );
}