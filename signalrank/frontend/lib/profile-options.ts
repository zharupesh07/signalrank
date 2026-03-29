import { api } from "@/lib/api";
import type { ProfileOptions } from "@/types";

export const PROFILE_OPTIONS_FALLBACK: ProfileOptions = {
  role_options: [
    "SAP SD Consultant",
    "SAP Functional Consultant",
    "SAP S/4HANA Consultant",
    "QA / Test Engineer",
    "QA Automation Engineer",
    "SDET",
    "AI/ML Engineer",
    "GenAI / LLM Engineer",
    "AI Platform Engineer",
    "Data Scientist",
    "Data Engineer",
    "Analytics Engineer",
    "MLOps/Platform Engineer",
    "Research Scientist",
    "Backend Engineer",
    "Full-Stack Engineer",
    "Frontend Engineer",
    "Mobile Engineer",
    "API / Integrations Engineer",
    "DevOps/SRE",
    "Platform Engineer",
    "Cloud Infrastructure Engineer",
    "Security Engineer",
    "Embedded / Systems Engineer",
    "Product Engineer",
  ],
  canonical_role_options: [
    "AI/ML Engineer",
    "GenAI / LLM Engineer",
    "AI Platform Engineer",
    "Data Scientist",
    "Data Engineer",
    "Analytics Engineer",
    "MLOps/Platform Engineer",
    "Research Scientist",
    "Backend Engineer",
    "Full-Stack Engineer",
    "Frontend Engineer",
    "Mobile Engineer",
    "API / Integrations Engineer",
    "DevOps/SRE",
    "Platform Engineer",
    "Cloud Infrastructure Engineer",
    "Security Engineer",
    "Embedded / Systems Engineer",
    "Product Engineer",
    "QA / Test Engineer",
    "SAP SD Consultant",
  ],
  location_options: [
    "Remote only",
    "Bangalore",
    "Hyderabad",
    "Mumbai",
    "Delhi/NCR",
    "Pune",
    "Any India",
    "Open to relocation",
  ],
  tier_options: [
    { label: "S-tier (FAANG, top startups)", value: "tier_s" },
    { label: "A-tier (strong tech companies)", value: "tier_a" },
    { label: "B-tier (good companies)", value: "tier_b" },
    { label: "Any company", value: "any" },
  ],
  title_penalty_rules: {
    strong: [],
    adjacent: [],
    hybrid: [],
  },
  company_tier_lists: {
    tier_ss: [],
    tier_s: [],
  },
};

export async function loadProfileOptions(token: string): Promise<ProfileOptions> {
  if (!token) {
    return PROFILE_OPTIONS_FALLBACK;
  }
  try {
    return await api.profile.options(token);
  } catch {
    return PROFILE_OPTIONS_FALLBACK;
  }
}
