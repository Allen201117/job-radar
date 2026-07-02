-- Seed overseas crawl regions for already-proven foreign ATS sources.
-- Scope is intentionally conservative:
--   - only IDs read from live sources on 2026-07-02
--   - only enabled http sources
--   - excludes browser/playwright sources such as Google for separate capacity review
--   - leaves disabled duplicate/experimental sources unchanged

with target(id) as (
  values
    ('84642913-4231-428f-8f70-3681ecf15359'::uuid), -- amazon / Amazon
    ('b0ad8b1d-ee93-4efe-a718-fd6f3782f442'::uuid), -- eightfold / Bayer
    ('861cf575-b161-409f-943d-8c7cf14ef298'::uuid), -- eightfold / STMicroelectronics
    ('8327a3e6-8453-4c7e-8a68-1a2e192ea282'::uuid), -- eightfold / HSBC
    ('c656f414-0479-424d-994e-0c671d7435b4'::uuid), -- eightfold / AstraZeneca
    ('c86d4fce-26d5-45b0-965f-1bdda89b02f4'::uuid), -- greenhouse / Adyen
    ('468f4655-a17c-4f25-9b1b-85c6c8a99bd7'::uuid), -- greenhouse / Agoda
    ('7c882b16-9842-4232-8456-a023556d6c11'::uuid), -- greenhouse / Akuna Capital
    ('8b6268fd-a5a5-478d-869c-d2b151b1cafd'::uuid), -- greenhouse / Anthropic
    ('d61a9ddf-052f-41d2-a724-08886a6a953d'::uuid), -- greenhouse / Cloudflare
    ('23267f3e-e011-4366-afd2-0518155d4ddc'::uuid), -- greenhouse / Discord
    ('0ff4a71f-0892-4ec8-9d1e-6b1808c83e13'::uuid), -- greenhouse / DRW
    ('0b1f151d-6cd8-4950-80b9-f39c8d88e4ee'::uuid), -- greenhouse / Elastic
    ('62864abd-f0ed-43c1-b2c3-7efa48db32fc'::uuid), -- greenhouse / Flow Traders
    ('da8119d6-42e7-41a0-8532-bf5e29e7e62c'::uuid), -- greenhouse / Hasbro
    ('40205c19-428a-411e-8876-4b3d7740268f'::uuid), -- greenhouse / IMC Trading
    ('460e229f-96d3-42ac-bb18-694cba212306'::uuid), -- greenhouse / Jane Street
    ('8859a6c8-beb5-4b29-a70f-f4705241fac0'::uuid), -- greenhouse / Jump Trading
    ('29ca0684-f128-4540-9390-93cd21a9f17c'::uuid), -- greenhouse / MongoDB
    ('7867b378-b311-449f-b9a5-0ed01d8ac1d0'::uuid), -- greenhouse / OKX
    ('31b936cb-dd4d-4fe3-9eb1-a62f99435691'::uuid), -- greenhouse / On
    ('41ad7e05-608a-4694-b0df-50a98e5d57ef'::uuid), -- greenhouse / Point72
    ('c65ebec8-4268-4205-9037-4588a3eb4de9'::uuid), -- greenhouse / Samsara
    ('21ecc856-f2a7-45a5-ab56-e753f9ecaaa2'::uuid), -- greenhouse / Squarepoint
    ('3cda46aa-acab-4c20-9bdd-a063e555c0c9'::uuid), -- greenhouse / Stripe
    ('f8a556d5-c4d3-4a81-bd21-e3ac0f6380d0'::uuid), -- greenhouse / Twilio
    ('a70b7575-a69b-4f42-99b1-e8219cb74c6b'::uuid), -- greenhouse / WorldQuant
    ('77fba3eb-de8b-4969-b863-e54eb5b2bdf3'::uuid), -- greenhouse / Zscaler
    ('4785938f-9efb-46a0-9754-6b997deff7f0'::uuid), -- greenhouse / Riot Games
    ('c1a55342-4d39-4f52-ac7c-e6c1574d9deb'::uuid), -- greenhouse / Airbnb
    ('49e2c707-ec29-4ae8-9efc-1a1422a626b3'::uuid), -- lever / Animoca Brands
    ('61f62365-9974-4898-a135-b4d9ecc69a81'::uuid), -- lever / Binance
    ('60f50250-7a95-459d-a88a-f99afb41a966'::uuid), -- microsoft / Microsoft
    ('61c86307-c3cd-4295-8c1b-57f962483e49'::uuid), -- oracle / Dell
    ('7dbb3ec0-4ad3-497d-8f16-cf1ed3c6be65'::uuid), -- oracle / Nokia
    ('b3ca9c04-e38c-4286-b2f5-f9d036b52710'::uuid), -- oracle / BNY Mellon
    ('7fbdf9b7-7975-4c98-941a-85ec0812957f'::uuid), -- oracle / American Express
    ('4b6eaed9-e830-4eef-9341-bf83f8c44868'::uuid), -- oracle / Emerson
    ('e3f38f48-4b65-455d-b65b-e7ad49228376'::uuid), -- oracle / Honeywell
    ('6e5e0918-4771-49d9-9849-968ff1608a47'::uuid), -- phenom / AMD
    ('3dcfb4be-de09-40e0-b37c-9080989b6d72'::uuid), -- phenom / PepsiCo
    ('3843f0d8-1cfa-478f-b166-7bfcbd12e7fb'::uuid), -- workday / 3M
    ('44318297-9c83-4104-ac20-296891b73719'::uuid), -- workday / Autodesk
    ('8d35c01a-7bb1-4acb-bcbf-82ab6cb6b4bb'::uuid), -- workday / Cadence
    ('25e0826d-af47-4abd-bcad-e815ff76b63b'::uuid), -- workday / Citi
    ('1d045b18-a5aa-4216-b5f8-7abb5515fc2a'::uuid), -- workday / GE HealthCare
    ('bec3d20d-29e4-49d2-92ee-22a2dfbdab32'::uuid), -- workday / Kenvue
    ('c1b03327-42f5-45bf-b113-05d14f44d977'::uuid), -- workday / Marvell
    ('c3b016c7-8766-49a6-adf4-d0d6ecfb8b5f'::uuid), -- workday / Mastercard
    ('4f5554b6-2300-4936-b506-a60780fbe244'::uuid), -- workday / MSD
    ('ae062ee6-00d3-4bbc-a203-b02ca9798ae6'::uuid), -- workday / Nike
    ('54a24eea-582b-42d0-bd02-64ad55a36a50'::uuid), -- workday / NVIDIA
    ('ef31fad1-23a5-44d9-af60-6a1607e86a43'::uuid), -- workday / Pfizer
    ('99993504-055e-472b-a7b1-87a6e83287c5'::uuid), -- workday / Rockwell Automation
    ('862d789c-c02c-470f-88a1-e08c56058880'::uuid), -- workday / Stellantis
    ('c489f1d4-e971-4843-a308-f464325f24e5'::uuid), -- workday / UPS
    ('05e8c579-1ed7-4cb5-90cf-4f029c9027fd'::uuid), -- workday / Visa
    ('6210c877-5c6d-46a6-b6bf-f5606fba3460'::uuid), -- workday / Workday
    ('4d3965c5-5ed8-4d4c-ad48-c011a7c3f151'::uuid), -- workday / Danaher
    ('77887073-8199-430e-b5d6-b0b929e562b8'::uuid), -- workday / ADI
    ('24565c59-c8a3-49e6-bed2-a3daed7fad02'::uuid), -- workday / Mondelez
    ('794f684a-8f4e-4e88-86cb-5300214d0f84'::uuid), -- workday / Pernod Ricard
    ('1945b7c4-811c-469d-bdce-37a3d46b1f55'::uuid), -- workday / BorgWarner
    ('21ed8657-184e-4289-8b0e-fb89b76c24d9'::uuid), -- workday / Broadcom
    ('e03b646e-8d56-488a-9292-ffd7f0e20f3d'::uuid), -- workday / Kraft Heinz
    ('694b1427-cf27-4ac2-adb3-4d54a8bca778'::uuid), -- workday / Caterpillar
    ('40141218-c8fe-49ef-9ff6-4786d4c6760c'::uuid), -- workday / Coca-Cola
    ('d34063b1-3b3b-4d4d-b7e0-d3e3dc0a8a38'::uuid), -- workday / Stryker
    ('47b35446-7e96-47d2-9a5a-4c37d0eb5390'::uuid), -- workday / Gilead
    ('32f5df94-cb89-4f37-945a-427bd821cd2b'::uuid), -- workday / Illumina
    ('110120d9-22c6-4b74-8953-0c6f868d8974'::uuid), -- workday / Otis
    ('cafc0f13-9e0f-41e0-93c1-06854acd137f'::uuid), -- workday / Aptiv
    ('33ef4319-bcc6-4b06-91d4-b3f6af2f0d57'::uuid), -- workday / Amgen
    ('156943ac-5e9d-4147-9cc5-e68cad371f94'::uuid), -- workday / Manulife
    ('a1b5d0e0-4e31-4953-acce-1f37f3515d99'::uuid), -- workday / Applied Materials
    ('634eaec0-fbf4-42b4-b56d-22aaa2de5e9b'::uuid), -- workday / Carrier
    ('82a3ce5e-12c1-46f7-bbbb-a7c55c85aec7'::uuid), -- workday / Johnson & Johnson
    ('59f5fed9-038b-4e17-982d-57fb08865e55'::uuid), -- workday / Deutsche Bank
    ('7753ad28-9f9f-4314-87af-baef2e211744'::uuid), -- workday / Cisco
    ('4ad0df53-56c5-45d8-95f1-eb08d7dfdf53'::uuid), -- workday / NXP
    ('049eb00d-8722-41e2-9d92-9c248b6d1ad2'::uuid), -- workday / HP
    ('b730e188-bdfd-4614-abb8-7ee1ea516185'::uuid), -- workday / HPE
    ('6d245f76-92a3-4771-bdfe-a62d681f8de7'::uuid), -- workday / Morgan Stanley
    ('b734c555-ec48-404e-a394-d936ff2ee1fd'::uuid), -- workday / DuPont
    ('6b54d956-44bb-4117-a3c2-98a0d17b37df'::uuid), -- workday / Takeda
    ('97ecf3e6-a632-44d0-ac4c-f01fe9bb26a9'::uuid), -- workday / Johnson Controls
    ('3f92cc10-675f-43ef-9af2-150222926699'::uuid), -- workday / Biogen
    ('91834367-caad-43b1-a8b7-2ff29a87ff65'::uuid), -- workday / Alcon
    ('e4ee057c-b262-4ffc-a531-f5bd79b87c1f'::uuid), -- workday / Edwards Lifesciences
    ('95f5739b-d061-4683-afeb-304ab9a864d3'::uuid), -- workday / Trane
    ('f487c6f3-123c-40ab-91a9-078dc9246118'::uuid), -- workday / ResMed
    ('e8aec9cf-f64a-468d-a411-65deed93be98'::uuid), -- workday / BMS
    ('90327687-2224-4b84-b537-fd34f1f95f2b'::uuid), -- workday / KLA
    ('02828432-e044-4a7d-9c03-65d5234503b3'::uuid), -- workday / Air Products
    ('acf002f0-7420-496c-867c-37126bb9c34d'::uuid), -- workday / Roche
    ('be51a473-88f9-4641-8db6-6b30eedea4d1'::uuid), -- workday / Micron
    ('7dab5853-ab9b-4dc7-b94b-0f18b44e097f'::uuid), -- workday / Medtronic
    ('6c667d83-2ec8-4086-8306-4f2ba5320e31'::uuid), -- workday / Intel
    ('294c69a2-23c0-491b-b7f4-91ed709a8c40'::uuid), -- workday / GSK
    ('41d6137a-4c76-42da-8579-53420513ef6c'::uuid), -- workday / Novartis
    ('8971afb9-a89a-4f37-8e3a-53ec649ffe9f'::uuid), -- workday / BlackRock
    ('e7ad9852-56a5-4105-866f-d18b7360da4d'::uuid), -- workday / Sanofi
    ('1c9ef9aa-0423-4b40-9669-89897792a495'::uuid), -- workday / Thermo Fisher
    ('385ae6fc-3ef1-4251-b378-a2137df2917d'::uuid), -- workday / Marsh McLennan
    ('a6e70322-1434-4c79-8a5e-bbbcabf06206'::uuid), -- workday / GM
    ('5f7c9918-42ba-4fcd-895d-eb405116e291'::uuid), -- workday / AstraZeneca
    ('9d03e9b7-c42c-478f-9ad6-0317e35c0378'::uuid), -- workday / Dow
    ('72ba71c9-87ad-4b69-a8e6-87d013764f13'::uuid), -- workday / Abbott
    ('8ef807fb-47a6-4af2-8b75-91384103454d'::uuid), -- workday / Philips
    ('f5e37642-e0e9-49fb-9d7a-aeaa9994bca9'::uuid), -- workday / Maersk
    ('23f5e380-69b2-40de-9f6b-0215574dafbf'::uuid) -- workday / Magna
)
update sources s
set regions = '{CN,US,SG,Remote}'::text[]
from target
where s.id = target.id
  and s.enabled is true
  and s.crawl_method = 'http'
  and s.adapter_name in (
    'workday', 'amazon', 'phenom', 'microsoft', 'greenhouse',
    'lever', 'oracle', 'eightfold', 'smartrecruiters', 'ashby'
  );
