# SS, S, A Tier Companies and Workday Portal Links

Source tiers: `signalrank/backend/config/base.yaml`
Verification source: local Postgres `jobs_raw` table, filtered where `job_url` contains `workday`.
Meaning of `Verified in DB = yes`: at least one Workday job URL for that company exists in current local DB snapshot.
Meaning of `Verified in DB = no`: no Workday URL for that company was found in current local DB snapshot. It does not prove company lacks Workday.

- Total companies checked: `103`
- Companies with Workday links verified in DB: `11`
- Additional companies found via web search: `4`
- Snapshot date: `2026-04-12`

## Verified Workday Portals

| Company | Tier | Workday Portal Base | Workday Host | Example Job URL |
|---|---|---|---|---|
| Salesforce | tier_ss | https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site | salesforce.wd12.myworkdayjobs.com | https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site/job/India---Bangalore/Consumer-Goods-Solution-Architect_JR330559 |
| Autodesk | tier_ss | https://autodesk.wd1.myworkdayjobs.com/en-US/Ext | autodesk.wd1.myworkdayjobs.com | https://autodesk.wd1.myworkdayjobs.com/en-US/Ext/job/Bengaluru-IND/Application-Security-Engineer_26WD95371-1 |
| Philips | tier_ss | https://philips.wd3.myworkdayjobs.com/en-US/jobs-and-careers | philips.wd3.myworkdayjobs.com | https://philips.wd3.myworkdayjobs.com/en-US/jobs-and-careers/job/Bangalore/Architect-I_577627 |
| Workday | tier_ss | https://workday.wd5.myworkdayjobs.com/en-US/Workday | workday.wd5.myworkdayjobs.com | https://workday.wd5.myworkdayjobs.com/en-US/Workday/job/INDChennai/P4---Senior-Quality-Assurance-Engineer_JR-0105532 |
| Nvidia | tier_s | https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite | nvidia.wd5.myworkdayjobs.com | https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/India-Bengaluru/ASIC-Engineer---New-College-Graduate-2026_JR2014620-1 |
| Palo Alto Networks | tier_a | https://paloaltonetworks.wd5.myworkdayjobs.com/panwexternalcareers | paloaltonetworks.wd5.myworkdayjobs.com | https://paloaltonetworks.wd5.myworkdayjobs.com/panwexternalcareers/job/Office---India---Bangalore-Bagmane-Tech-Park/Sr-Staff-ML-Engineer---Production---MLOps-Focus---GenAI-Security-Platform--Prisma-AIRS--NetSec-_JR-015011 |
| CrowdStrike | tier_a | https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers | crowdstrike.wd5.myworkdayjobs.com | https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers/job/India---Bangalore/Engineer-II---Cloud--Integrations-Platform_R28247 |
| Red Hat | tier_a | https://redhat.wd5.myworkdayjobs.com/en-US/jobs | redhat.wd5.myworkdayjobs.com | https://redhat.wd5.myworkdayjobs.com/en-US/jobs/job/Bangalore---Carina/Account-Solution-Architect_R-053762-1 |
| Marvell Technology | tier_a | https://marvell.wd1.myworkdayjobs.com/en-US/MarvellCareers | marvell.wd1.myworkdayjobs.com | https://marvell.wd1.myworkdayjobs.com/en-US/MarvellCareers/job/Bangalore/Analog-Design---Senior-Principal-Engineer_2601256 |
| KLA | tier_a | https://kla.wd1.myworkdayjobs.com/en-US/Search | kla.wd1.myworkdayjobs.com | https://kla.wd1.myworkdayjobs.com/en-US/Search/job/Chennai-India/AI-Architect---Manager_2634372 |
| Automation Anywhere | tier_a | https://automationanywhere.wd5.myworkdayjobs.com/en-US/AutomationAnywhereJobs | automationanywhere.wd5.myworkdayjobs.com | https://automationanywhere.wd5.myworkdayjobs.com/en-US/AutomationAnywhereJobs/job/Bengaluru-India/AI-Engineer_JR1266 |

## Web-Researched Additions, Not Yet Verified In DB

These were found from public web pages that point to company Workday job URLs, but I did not find matching rows in current local DB snapshot.

| Company | Tier | Why It Fits Your Profile | Workday Portal Base | Example Job URL | Evidence |
|---|---|---|---|---|---|
| Qualcomm | tier_a | AI systems, workflow automation, ML platform-adjacent infra, strong India/Taiwan hiring | https://qualcomm.wd12.myworkdayjobs.com/External | https://qualcomm.wd12.myworkdayjobs.com/External/job/Taipei-TWN/AI-SW-Engineer--Staff_3071600 | [104 AI SW Engineer listing](https://www.104.com.tw/job/8let9?jobsource=freshman2009) |
| Expedia Group | tier_a | GenAI platform leadership, LLM platform, orchestration, enterprise AI adoption | https://expedia.wd108.myworkdayjobs.com/search | not captured in DB | [LinkedIn post for Director, Gen AI Platform](https://www.linkedin.com/posts/magnomendoza_director-gen-ai-platform-activity-7398821905790693376-3QOf) |
| Dell Technologies | tier_a | LLM + agentic workflow + applied enterprise AI roles appear on Workday | https://dell.wd1.myworkdayjobs.com/External | https://dell.wd1.myworkdayjobs.com/External/job/Bangalore-India/Consultant-Data-Science-I9-_R270197 | [iimjobs Dell LLM role](https://www.iimjobs.com/j/dell-data-science-consultant-python-programmingllm-1579785) |
| BlackRock | tier_a | lower fit than infra/platform companies, but has Workday portal and platform/SRE style roles occasionally surface | https://blackrock.wd1.myworkdayjobs.com/en-US/BlackRock_Professional | not captured in DB | [Sohu repost linking official portal](https://www.sohu.com/a/524831380_121124286) |

## Best Fits For Your Profile

Highest-signal Workday companies for `Senior AI Platform Engineer / Staff AI Platform Engineer / Senior LLMOps Engineer`:

| Company | Tier | Verification Mode | Why It Stands Out |
|---|---|---|---|
| Salesforce | tier_ss | DB | Agentforce, platform, AI architecture, forward deployed paths |
| Workday | tier_ss | DB | platform-heavy engineering org, enterprise AI, strong infra depth |
| Nvidia | tier_s | DB | AI systems/platform credibility, infra-adjacent opportunities |
| Palo Alto Networks | tier_a | DB | GenAI security platform, MLOps/security-platform overlap |
| CrowdStrike | tier_a | DB | cloud platform + security AI runtime overlap |
| Red Hat | tier_a | DB | Kubernetes, platform, orchestration, infra-heavy fit |
| Qualcomm | tier_a | Web | AI software + workflow automation + ML systems |
| Expedia Group | tier_a | Web | explicit GenAI platform org |
| Dell Technologies | tier_a | Web | LLM/data science roles with enterprise deployment angle |

## tier_ss (4/32 verified in DB)

| Company | Verified in DB | Workday Portal Base | Workday Host | Example Job URL |
|---|---|---|---|---|
| Atlassian | no |  |  |  |
| Salesforce | yes | https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site | salesforce.wd12.myworkdayjobs.com | https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site/job/India---Bangalore/Consumer-Goods-Solution-Architect_JR330559 |
| Google | no |  |  |  |
| Adobe | no |  |  |  |
| Intuit | no |  |  |  |
| LinkedIn | no |  |  |  |
| HubSpot | no |  |  |  |
| Autodesk | yes | https://autodesk.wd1.myworkdayjobs.com/en-US/Ext | autodesk.wd1.myworkdayjobs.com | https://autodesk.wd1.myworkdayjobs.com/en-US/Ext/job/Bengaluru-IND/Application-Security-Engineer_26WD95371-1 |
| UKG | no |  |  |  |
| Elastic | no |  |  |  |
| GitLab | no |  |  |  |
| JetBrains | no |  |  |  |
| Spotify | no |  |  |  |
| Klarna | no |  |  |  |
| Adyen | no |  |  |  |
| Booking.com | no |  |  |  |
| Delivery Hero | no |  |  |  |
| Zalando | no |  |  |  |
| SAP | no |  |  |  |
| Siemens | no |  |  |  |
| Bosch | no |  |  |  |
| Philips | yes | https://philips.wd3.myworkdayjobs.com/en-US/jobs-and-careers | philips.wd3.myworkdayjobs.com | https://philips.wd3.myworkdayjobs.com/en-US/jobs-and-careers/job/Bangalore/Architect-I_577627 |
| ASML | no |  |  |  |
| ARM | no |  |  |  |
| Dynatrace | no |  |  |  |
| Contentful | no |  |  |  |
| Personio | no |  |  |  |
| Canonical | no |  |  |  |
| Grafana Labs | no |  |  |  |
| Miro | no |  |  |  |
| Notion | no |  |  |  |
| Workday | yes | https://workday.wd5.myworkdayjobs.com/en-US/Workday | workday.wd5.myworkdayjobs.com | https://workday.wd5.myworkdayjobs.com/en-US/Workday/job/INDChennai/P4---Senior-Quality-Assurance-Engineer_JR-0105532 |

## tier_s (1/26 verified in DB)

| Company | Verified in DB | Workday Portal Base | Workday Host | Example Job URL |
|---|---|---|---|---|
| Microsoft | no |  |  |  |
| ServiceNow | no |  |  |  |
| VMware | no |  |  |  |
| Cisco | no |  |  |  |
| Oracle | no |  |  |  |
| Netflix | no |  |  |  |
| Stripe | no |  |  |  |
| Snowflake | no |  |  |  |
| Databricks | no |  |  |  |
| Palantir | no |  |  |  |
| Scale AI | no |  |  |  |
| Weights and Biases | no |  |  |  |
| Hugging Face | no |  |  |  |
| OpenAI | no |  |  |  |
| Anthropic | no |  |  |  |
| Cohere | no |  |  |  |
| DeepMind | no |  |  |  |
| Apple | no |  |  |  |
| Meta | no |  |  |  |
| Nvidia | yes | https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite | nvidia.wd5.myworkdayjobs.com | https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/India-Bengaluru/ASIC-Engineer---New-College-Graduate-2026_JR2014620-1 |
| Freshworks | no |  |  |  |
| Zoho | no |  |  |  |
| AMD | no |  |  |  |
| Okta | no |  |  |  |
| Intel | no |  |  |  |
| Synopsys | no |  |  |  |

## tier_a (6/45 verified in DB)

| Company | Verified in DB | Workday Portal Base | Workday Host | Example Job URL |
|---|---|---|---|---|
| Amazon | no |  |  |  |
| Uber | no |  |  |  |
| Coinbase | no |  |  |  |
| Rippling | no |  |  |  |
| Flipkart | no |  |  |  |
| PhonePe | no |  |  |  |
| Razorpay | no |  |  |  |
| CRED | no |  |  |  |
| Meesho | no |  |  |  |
| Swiggy | no |  |  |  |
| Zomato | no |  |  |  |
| Dream11 | no |  |  |  |
| Groww | no |  |  |  |
| Zerodha | no |  |  |  |
| Walmart | no |  |  |  |
| Visa | no |  |  |  |
| Mastercard | no |  |  |  |
| Capital One | no |  |  |  |
| Airbnb | no |  |  |  |
| Shopify | no |  |  |  |
| Bloomberg | no |  |  |  |
| Qualcomm | no |  |  |  |
| Palo Alto Networks | yes | https://paloaltonetworks.wd5.myworkdayjobs.com/panwexternalcareers | paloaltonetworks.wd5.myworkdayjobs.com | https://paloaltonetworks.wd5.myworkdayjobs.com/panwexternalcareers/job/Office---India---Bangalore-Bagmane-Tech-Park/Sr-Staff-ML-Engineer---Production---MLOps-Focus---GenAI-Security-Platform--Prisma-AIRS--NetSec-_JR-015011 |
| CrowdStrike | yes | https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers | crowdstrike.wd5.myworkdayjobs.com | https://crowdstrike.wd5.myworkdayjobs.com/en-US/crowdstrikecareers/job/India---Bangalore/Engineer-II---Cloud--Integrations-Platform_R28247 |
| Datadog | no |  |  |  |
| Confluent | no |  |  |  |
| HashiCorp | no |  |  |  |
| MongoDB | no |  |  |  |
| Red Hat | yes | https://redhat.wd5.myworkdayjobs.com/en-US/jobs | redhat.wd5.myworkdayjobs.com | https://redhat.wd5.myworkdayjobs.com/en-US/jobs/job/Bangalore---Carina/Account-Solution-Architect_R-053762-1 |
| JPMorgan | no |  |  |  |
| Goldman Sachs | no |  |  |  |
| Morgan Stanley | no |  |  |  |
| BlackRock | no |  |  |  |
| Dell Technologies | no |  |  |  |
| Micron Technology | no |  |  |  |
| PayPal | no |  |  |  |
| eBay | no |  |  |  |
| Expedia Group | no |  |  |  |
| American Express | no |  |  |  |
| Warner Bros | no |  |  |  |
| Marvell Technology | yes | https://marvell.wd1.myworkdayjobs.com/en-US/MarvellCareers | marvell.wd1.myworkdayjobs.com | https://marvell.wd1.myworkdayjobs.com/en-US/MarvellCareers/job/Bangalore/Analog-Design---Senior-Principal-Engineer_2601256 |
| KLA | yes | https://kla.wd1.myworkdayjobs.com/en-US/Search | kla.wd1.myworkdayjobs.com | https://kla.wd1.myworkdayjobs.com/en-US/Search/job/Chennai-India/AI-Architect---Manager_2634372 |
| NetApp | no |  |  |  |
| Equinix | no |  |  |  |
| Automation Anywhere | yes | https://automationanywhere.wd5.myworkdayjobs.com/en-US/AutomationAnywhereJobs | automationanywhere.wd5.myworkdayjobs.com | https://automationanywhere.wd5.myworkdayjobs.com/en-US/AutomationAnywhereJobs/job/Bengaluru-India/AI-Engineer_JR1266 |
