import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { api } from "@/lib/api";

function decodeJwtPayload(token: string): Record<string, unknown> {
  const parts = token.split(".");
  if (parts.length !== 3) return {};
  const payload = Buffer.from(parts[1], "base64url").toString("utf-8");
  return JSON.parse(payload);
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  session: {
    maxAge: 60 * 60 * 24 * 7, // 7 days — matches backend JWT TTL
  },
  providers: [
    Credentials({
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
        desktopToken: { label: "Desktop Token", type: "text" },
      },
      async authorize(credentials) {
        const desktopToken = credentials?.desktopToken as string | undefined;
        if (
          desktopToken &&
          (process.env.SIGNALRANK_MODE === "desktop" ||
            process.env.NEXT_PUBLIC_SIGNALRANK_MODE === "desktop")
        ) {
          const decoded = decodeJwtPayload(desktopToken);
          return {
            id: String(decoded.sub ?? "desktop"),
            email: String(decoded.email ?? "local@signalrank.desktop"),
            accessToken: desktopToken,
            isAdmin: (decoded.is_admin as boolean) ?? true,
          };
        }
        if (!credentials?.email || !credentials?.password) return null;
        try {
          const data = await api.auth.login(
            credentials.email as string,
            credentials.password as string
          );
          const decoded = decodeJwtPayload(data.access_token);
          return {
            id: "user",
            email: credentials.email as string,
            accessToken: data.access_token,
            isAdmin: (decoded.is_admin as boolean) ?? false,
          };
        } catch (error) {
          console.error("Credentials authorize failed", error);
          return null;
        }
      },
    }),
  ],
  callbacks: {
    async jwt({ token, user }) {
      if (user) {
        token.accessToken = (user as { accessToken?: string }).accessToken;
        token.isAdmin = (user as { isAdmin?: boolean }).isAdmin;
      }
      return token;
    },
    async session({ session, token }) {
      (session as { accessToken?: string }).accessToken = token.accessToken as string;
      (session as { isAdmin?: boolean }).isAdmin = (token.isAdmin as boolean) ?? false;
      return session;
    },
  },
  pages: {
    signIn: "/login",
  },
});
