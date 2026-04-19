import { NextResponse } from "next/server";
import { auth } from "@/auth";

const PROTECTED_PATHS = ["/dashboard", "/jobs", "/tracker", "/settings", "/admin", "/onboarding"];

export default auth((req) => {
  const { pathname, search } = req.nextUrl;
  const isProtected = PROTECTED_PATHS.some(
    (path) => pathname === path || pathname.startsWith(`${path}/`)
  );

  if (!isProtected || req.auth) {
    return NextResponse.next();
  }

  const loginUrl = new URL("/login", req.nextUrl.origin);
  loginUrl.searchParams.set("callbackUrl", `${pathname}${search}`);
  return NextResponse.redirect(loginUrl);
});

export const config = {
  matcher: ["/dashboard/:path*", "/jobs/:path*", "/tracker/:path*", "/settings/:path*", "/admin/:path*", "/onboarding/:path*"],
};
