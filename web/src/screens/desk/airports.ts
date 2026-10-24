/**
 * Airport lookup for the desk's autocomplete. CONTRACTS §3 has no airports route yet, so this is a
 * static table of names and codes only (requested: GET /api/airports). The server stays the judge of
 * what it can run: an airport it doesn't know comes back as a plain 422, and any 4-letter ICAO code
 * can be typed as is. `tz` is the IANA zone, used only to say which local date is meant.
 *
 * Rows: IATA|ICAO|name|city|country|tz|aliases. Roughly ordered by size within each region, which
 * breaks ties in the ranking.
 */
const TABLE = `
DUB|EIDW|Dublin|Dublin|IE|Europe/Dublin|
ORK|EICK|Cork|Cork|IE|Europe/Dublin|
SNN|EINN|Shannon|Shannon|IE|Europe/Dublin|limerick
NOC|EIKN|Knock|Knock|IE|Europe/Dublin|ireland west
KIR|EIKY|Kerry|Kerry|IE|Europe/Dublin|farranfore
LHR|EGLL|London Heathrow|London|GB|Europe/London|heathrow
LGW|EGKK|London Gatwick|London|GB|Europe/London|gatwick
STN|EGSS|London Stansted|London|GB|Europe/London|stansted
LTN|EGGW|London Luton|London|GB|Europe/London|luton
LCY|EGLC|London City|London|GB|Europe/London|
SEN|EGMC|London Southend|London|GB|Europe/London|southend
MAN|EGCC|Manchester|Manchester|GB|Europe/London|
EDI|EGPH|Edinburgh|Edinburgh|GB|Europe/London|
BHX|EGBB|Birmingham|Birmingham|GB|Europe/London|
GLA|EGPF|Glasgow|Glasgow|GB|Europe/London|
BRS|EGGD|Bristol|Bristol|GB|Europe/London|
BFS|EGAA|Belfast International|Belfast|GB|Europe/London|aldergrove
BHD|EGAC|Belfast City|Belfast|GB|Europe/London|george best
NCL|EGNT|Newcastle|Newcastle|GB|Europe/London|
LPL|EGGP|Liverpool|Liverpool|GB|Europe/London|john lennon
EMA|EGNX|East Midlands|Nottingham|GB|Europe/London|
LBA|EGNM|Leeds Bradford|Leeds|GB|Europe/London|
ABZ|EGPD|Aberdeen|Aberdeen|GB|Europe/London|
CWL|EGFF|Cardiff|Cardiff|GB|Europe/London|
SOU|EGHI|Southampton|Southampton|GB|Europe/London|
EXT|EGTE|Exeter|Exeter|GB|Europe/London|
INV|EGPE|Inverness|Inverness|GB|Europe/London|
JER|EGJJ|Jersey|Jersey|JE|Europe/Jersey|
GCI|EGJB|Guernsey|Guernsey|GG|Europe/Guernsey|
IOM|EGNS|Isle of Man|Ronaldsway|IM|Europe/Isle_of_Man|
CDG|LFPG|Paris Charles de Gaulle|Paris|FR|Europe/Paris|roissy
ORY|LFPO|Paris Orly|Paris|FR|Europe/Paris|orly
BVA|LFOB|Paris Beauvais|Paris|FR|Europe/Paris|beauvais
NCE|LFMN|Nice|Nice|FR|Europe/Paris|cote d'azur
LYS|LFLL|Lyon|Lyon|FR|Europe/Paris|saint-exupery
MRS|LFML|Marseille|Marseille|FR|Europe/Paris|provence
TLS|LFBO|Toulouse|Toulouse|FR|Europe/Paris|blagnac
BOD|LFBD|Bordeaux|Bordeaux|FR|Europe/Paris|merignac
NTE|LFRS|Nantes|Nantes|FR|Europe/Paris|
BSL|LFSB|Basel-Mulhouse|Basel|FR|Europe/Paris|euroairport mulhouse freiburg
MPL|LFMT|Montpellier|Montpellier|FR|Europe/Paris|
LIL|LFQQ|Lille|Lille|FR|Europe/Paris|
SXB|LFST|Strasbourg|Strasbourg|FR|Europe/Paris|
BIQ|LFBZ|Biarritz|Biarritz|FR|Europe/Paris|
RNS|LFRN|Rennes|Rennes|FR|Europe/Paris|
BES|LFRB|Brest|Brest|FR|Europe/Paris|
FRA|EDDF|Frankfurt|Frankfurt|DE|Europe/Berlin|
MUC|EDDM|Munich|Munich|DE|Europe/Berlin|munchen
BER|EDDB|Berlin Brandenburg|Berlin|DE|Europe/Berlin|
DUS|EDDL|Düsseldorf|Düsseldorf|DE|Europe/Berlin|
HAM|EDDH|Hamburg|Hamburg|DE|Europe/Berlin|
CGN|EDDK|Cologne Bonn|Cologne|DE|Europe/Berlin|koln bonn
STR|EDDS|Stuttgart|Stuttgart|DE|Europe/Berlin|
HAJ|EDDV|Hannover|Hannover|DE|Europe/Berlin|hanover
NUE|EDDN|Nuremberg|Nuremberg|DE|Europe/Berlin|nurnberg
LEJ|EDDP|Leipzig/Halle|Leipzig|DE|Europe/Berlin|halle
BRE|EDDW|Bremen|Bremen|DE|Europe/Berlin|
DRS|EDDC|Dresden|Dresden|DE|Europe/Berlin|
DTM|EDLW|Dortmund|Dortmund|DE|Europe/Berlin|
FMO|EDDG|Münster Osnabrück|Münster|DE|Europe/Berlin|osnabruck
NRN|EDLV|Weeze|Weeze|DE|Europe/Berlin|niederrhein
FMM|EDJA|Memmingen|Memmingen|DE|Europe/Berlin|allgau
HHN|EDFH|Frankfurt-Hahn|Hahn|DE|Europe/Berlin|
AMS|EHAM|Amsterdam Schiphol|Amsterdam|NL|Europe/Amsterdam|schiphol
EIN|EHEH|Eindhoven|Eindhoven|NL|Europe/Amsterdam|
RTM|EHRD|Rotterdam The Hague|Rotterdam|NL|Europe/Amsterdam|den haag
MST|EHBK|Maastricht Aachen|Maastricht|NL|Europe/Amsterdam|
BRU|EBBR|Brussels|Brussels|BE|Europe/Brussels|zaventem bruxelles
CRL|EBCI|Brussels South Charleroi|Charleroi|BE|Europe/Brussels|
LUX|ELLX|Luxembourg|Luxembourg|LU|Europe/Luxembourg|findel
ZRH|LSZH|Zürich|Zürich|CH|Europe/Zurich|kloten
GVA|LSGG|Geneva|Geneva|CH|Europe/Zurich|geneve cointrin
VIE|LOWW|Vienna|Vienna|AT|Europe/Vienna|wien schwechat
SZG|LOWS|Salzburg|Salzburg|AT|Europe/Vienna|
INN|LOWI|Innsbruck|Innsbruck|AT|Europe/Vienna|
GRZ|LOWG|Graz|Graz|AT|Europe/Vienna|
MAD|LEMD|Madrid Barajas|Madrid|ES|Europe/Madrid|barajas
BCN|LEBL|Barcelona El Prat|Barcelona|ES|Europe/Madrid|el prat
AGP|LEMG|Málaga|Málaga|ES|Europe/Madrid|costa del sol
PMI|LEPA|Palma de Mallorca|Palma|ES|Europe/Madrid|mallorca majorca
ALC|LEAL|Alicante|Alicante|ES|Europe/Madrid|elche
VLC|LEVC|Valencia|Valencia|ES|Europe/Madrid|
SVQ|LEZL|Seville|Seville|ES|Europe/Madrid|sevilla
BIO|LEBB|Bilbao|Bilbao|ES|Europe/Madrid|
IBZ|LEIB|Ibiza|Ibiza|ES|Europe/Madrid|
TFS|GCTS|Tenerife South|Tenerife|ES|Atlantic/Canary|canary islands
TFN|GCXO|Tenerife North|Tenerife|ES|Atlantic/Canary|los rodeos
LPA|GCLP|Gran Canaria|Las Palmas|ES|Atlantic/Canary|canary islands
ACE|GCRR|Lanzarote|Lanzarote|ES|Atlantic/Canary|arrecife
FUE|GCFV|Fuerteventura|Fuerteventura|ES|Atlantic/Canary|
MAH|LEMH|Menorca|Mahón|ES|Europe/Madrid|minorca
SCQ|LEST|Santiago de Compostela|Santiago|ES|Europe/Madrid|
GRO|LEGE|Girona|Girona|ES|Europe/Madrid|costa brava
REU|LERS|Reus|Reus|ES|Europe/Madrid|
SDR|LEXJ|Santander|Santander|ES|Europe/Madrid|
OVD|LEAS|Asturias|Oviedo|ES|Europe/Madrid|
RMU|LEMI|Región de Murcia|Murcia|ES|Europe/Madrid|corvera
LIS|LPPT|Lisbon|Lisbon|PT|Europe/Lisbon|lisboa humberto delgado
OPO|LPPR|Porto|Porto|PT|Europe/Lisbon|oporto
FAO|LPFR|Faro|Faro|PT|Europe/Lisbon|algarve
FNC|LPMA|Madeira|Funchal|PT|Atlantic/Madeira|
PDL|LPPD|Ponta Delgada|Ponta Delgada|PT|Atlantic/Azores|azores
FCO|LIRF|Rome Fiumicino|Rome|IT|Europe/Rome|fiumicino roma
CIA|LIRA|Rome Ciampino|Rome|IT|Europe/Rome|ciampino roma
MXP|LIMC|Milan Malpensa|Milan|IT|Europe/Rome|malpensa milano
LIN|LIML|Milan Linate|Milan|IT|Europe/Rome|linate milano
BGY|LIME|Milan Bergamo|Bergamo|IT|Europe/Rome|orio al serio
VCE|LIPZ|Venice Marco Polo|Venice|IT|Europe/Rome|venezia
TSF|LIPH|Treviso|Treviso|IT|Europe/Rome|venice treviso
NAP|LIRN|Naples|Naples|IT|Europe/Rome|napoli capodichino
BLQ|LIPE|Bologna|Bologna|IT|Europe/Rome|
FLR|LIRQ|Florence|Florence|IT|Europe/Rome|firenze peretola
PSA|LIRP|Pisa|Pisa|IT|Europe/Rome|galilei
CTA|LICC|Catania|Catania|IT|Europe/Rome|sicily
PMO|LICJ|Palermo|Palermo|IT|Europe/Rome|sicily
BRI|LIBD|Bari|Bari|IT|Europe/Rome|
TRN|LIMF|Turin|Turin|IT|Europe/Rome|torino caselle
CAG|LIEE|Cagliari|Cagliari|IT|Europe/Rome|sardinia
OLB|LIEO|Olbia|Olbia|IT|Europe/Rome|sardinia
VRN|LIPX|Verona|Verona|IT|Europe/Rome|
GOA|LIMJ|Genoa|Genoa|IT|Europe/Rome|genova
BDS|LIBR|Brindisi|Brindisi|IT|Europe/Rome|
SUF|LICA|Lamezia Terme|Lamezia|IT|Europe/Rome|calabria
ATH|LGAV|Athens|Athens|GR|Europe/Athens|eleftherios venizelos
SKG|LGTS|Thessaloniki|Thessaloniki|GR|Europe/Athens|
HER|LGIR|Heraklion|Heraklion|GR|Europe/Athens|crete
RHO|LGRP|Rhodes|Rhodes|GR|Europe/Athens|
CFU|LGKR|Corfu|Corfu|GR|Europe/Athens|kerkyra
CHQ|LGSA|Chania|Chania|GR|Europe/Athens|crete
JTR|LGSR|Santorini|Santorini|GR|Europe/Athens|thira
JMK|LGMK|Mykonos|Mykonos|GR|Europe/Athens|
KGS|LGKO|Kos|Kos|GR|Europe/Athens|
ZTH|LGZA|Zakynthos|Zakynthos|GR|Europe/Athens|zante
MLA|LMML|Malta|Luqa|MT|Europe/Malta|
LCA|LCLK|Larnaca|Larnaca|CY|Asia/Nicosia|cyprus
PFO|LCPH|Paphos|Paphos|CY|Asia/Nicosia|cyprus
CPH|EKCH|Copenhagen|Copenhagen|DK|Europe/Copenhagen|kastrup kobenhavn
BLL|EKBI|Billund|Billund|DK|Europe/Copenhagen|
AAL|EKYT|Aalborg|Aalborg|DK|Europe/Copenhagen|
OSL|ENGM|Oslo|Oslo|NO|Europe/Oslo|gardermoen
BGO|ENBR|Bergen|Bergen|NO|Europe/Oslo|flesland
SVG|ENZV|Stavanger|Stavanger|NO|Europe/Oslo|sola
TRD|ENVA|Trondheim|Trondheim|NO|Europe/Oslo|vaernes
TOS|ENTC|Tromsø|Tromsø|NO|Europe/Oslo|
ARN|ESSA|Stockholm Arlanda|Stockholm|SE|Europe/Stockholm|arlanda
GOT|ESGG|Gothenburg|Gothenburg|SE|Europe/Stockholm|goteborg landvetter
NYO|ESKN|Stockholm Skavsta|Stockholm|SE|Europe/Stockholm|skavsta
MMX|ESMS|Malmö|Malmö|SE|Europe/Stockholm|
HEL|EFHK|Helsinki|Helsinki|FI|Europe/Helsinki|vantaa
KEF|BIKF|Reykjavík Keflavík|Reykjavík|IS|Atlantic/Reykjavik|keflavik iceland
RIX|EVRA|Riga|Riga|LV|Europe/Riga|
TLL|EETN|Tallinn|Tallinn|EE|Europe/Tallinn|
VNO|EYVI|Vilnius|Vilnius|LT|Europe/Vilnius|
KUN|EYKA|Kaunas|Kaunas|LT|Europe/Vilnius|
WAW|EPWA|Warsaw Chopin|Warsaw|PL|Europe/Warsaw|warszawa okecie
WMI|EPMO|Warsaw Modlin|Warsaw|PL|Europe/Warsaw|modlin
KRK|EPKK|Kraków|Kraków|PL|Europe/Warsaw|krakow balice
GDN|EPGD|Gdańsk|Gdańsk|PL|Europe/Warsaw|gdansk
WRO|EPWR|Wrocław|Wrocław|PL|Europe/Warsaw|
KTW|EPKT|Katowice|Katowice|PL|Europe/Warsaw|
POZ|EPPO|Poznań|Poznań|PL|Europe/Warsaw|
PRG|LKPR|Prague|Prague|CZ|Europe/Prague|praha vaclav havel
BTS|LZIB|Bratislava|Bratislava|SK|Europe/Bratislava|
BUD|LHBP|Budapest|Budapest|HU|Europe/Budapest|ferenc liszt
OTP|LROP|Bucharest Otopeni|Bucharest|RO|Europe/Bucharest|henri coanda
CLJ|LRCL|Cluj-Napoca|Cluj|RO|Europe/Bucharest|
SOF|LBSF|Sofia|Sofia|BG|Europe/Sofia|
VAR|LBWN|Varna|Varna|BG|Europe/Sofia|
BOJ|LBBG|Burgas|Burgas|BG|Europe/Sofia|
ZAG|LDZA|Zagreb|Zagreb|HR|Europe/Zagreb|
SPU|LDSP|Split|Split|HR|Europe/Zagreb|
DBV|LDDU|Dubrovnik|Dubrovnik|HR|Europe/Zagreb|
LJU|LJLJ|Ljubljana|Ljubljana|SI|Europe/Ljubljana|brnik
BEG|LYBE|Belgrade|Belgrade|RS|Europe/Belgrade|beograd nikola tesla
IST|LTFM|Istanbul|Istanbul|TR|Europe/Istanbul|
SAW|LTFJ|Istanbul Sabiha Gökçen|Istanbul|TR|Europe/Istanbul|sabiha gokcen
AYT|LTAI|Antalya|Antalya|TR|Europe/Istanbul|
TIA|LATI|Tirana|Tirana|AL|Europe/Tirane|
SKP|LWSK|Skopje|Skopje|MK|Europe/Skopje|
TGD|LYPG|Podgorica|Podgorica|ME|Europe/Podgorica|
SJJ|LQSA|Sarajevo|Sarajevo|BA|Europe/Sarajevo|
GIB|LXGB|Gibraltar|Gibraltar|GI|Europe/Gibraltar|
JFK|KJFK|New York JFK|New York|US|America/New_York|kennedy nyc
EWR|KEWR|Newark|New York|US|America/New_York|nyc new jersey
LGA|KLGA|New York LaGuardia|New York|US|America/New_York|laguardia nyc
BOS|KBOS|Boston Logan|Boston|US|America/New_York|logan
ORD|KORD|Chicago O'Hare|Chicago|US|America/Chicago|ohare
MDW|KMDW|Chicago Midway|Chicago|US|America/Chicago|midway
IAD|KIAD|Washington Dulles|Washington|US|America/New_York|dulles dc
DCA|KDCA|Washington Reagan|Washington|US|America/New_York|reagan national dc
BWI|KBWI|Baltimore/Washington|Baltimore|US|America/New_York|
PHL|KPHL|Philadelphia|Philadelphia|US|America/New_York|
ATL|KATL|Atlanta|Atlanta|US|America/New_York|hartsfield jackson
MIA|KMIA|Miami|Miami|US|America/New_York|
FLL|KFLL|Fort Lauderdale|Fort Lauderdale|US|America/New_York|
MCO|KMCO|Orlando|Orlando|US|America/New_York|
TPA|KTPA|Tampa|Tampa|US|America/New_York|
RSW|KRSW|Fort Myers|Fort Myers|US|America/New_York|
JAX|KJAX|Jacksonville|Jacksonville|US|America/New_York|
CLT|KCLT|Charlotte|Charlotte|US|America/New_York|douglas
RDU|KRDU|Raleigh-Durham|Raleigh|US|America/New_York|
DTW|KDTW|Detroit|Detroit|US|America/Detroit|metro wayne
CLE|KCLE|Cleveland|Cleveland|US|America/New_York|hopkins
PIT|KPIT|Pittsburgh|Pittsburgh|US|America/New_York|
CMH|KCMH|Columbus|Columbus|US|America/New_York|john glenn
CVG|KCVG|Cincinnati|Cincinnati|US|America/New_York|northern kentucky
IND|KIND|Indianapolis|Indianapolis|US|America/Indiana/Indianapolis|
BDL|KBDL|Hartford Bradley|Hartford|US|America/New_York|bradley
PVD|KPVD|Providence|Providence|US|America/New_York|
DFW|KDFW|Dallas/Fort Worth|Dallas|US|America/Chicago|
DAL|KDAL|Dallas Love Field|Dallas|US|America/Chicago|love field
IAH|KIAH|Houston Bush|Houston|US|America/Chicago|george bush intercontinental
HOU|KHOU|Houston Hobby|Houston|US|America/Chicago|hobby
AUS|KAUS|Austin|Austin|US|America/Chicago|bergstrom
SAT|KSAT|San Antonio|San Antonio|US|America/Chicago|
MSP|KMSP|Minneapolis–St Paul|Minneapolis|US|America/Chicago|saint paul
STL|KSTL|St. Louis|St. Louis|US|America/Chicago|saint louis lambert
MCI|KMCI|Kansas City|Kansas City|US|America/Chicago|
MKE|KMKE|Milwaukee|Milwaukee|US|America/Chicago|mitchell
BNA|KBNA|Nashville|Nashville|US|America/Chicago|
MSY|KMSY|New Orleans|New Orleans|US|America/Chicago|louis armstrong
DEN|KDEN|Denver|Denver|US|America/Denver|
SLC|KSLC|Salt Lake City|Salt Lake City|US|America/Denver|
PHX|KPHX|Phoenix|Phoenix|US|America/Phoenix|sky harbor
LAS|KLAS|Las Vegas|Las Vegas|US|America/Los_Angeles|harry reid
LAX|KLAX|Los Angeles|Los Angeles|US|America/Los_Angeles|
SFO|KSFO|San Francisco|San Francisco|US|America/Los_Angeles|bay area
OAK|KOAK|Oakland|Oakland|US|America/Los_Angeles|bay area
SJC|KSJC|San José|San José|US|America/Los_Angeles|bay area mineta
SAN|KSAN|San Diego|San Diego|US|America/Los_Angeles|lindbergh
SNA|KSNA|Orange County|Santa Ana|US|America/Los_Angeles|john wayne
BUR|KBUR|Burbank|Burbank|US|America/Los_Angeles|hollywood
SMF|KSMF|Sacramento|Sacramento|US|America/Los_Angeles|
SEA|KSEA|Seattle–Tacoma|Seattle|US|America/Los_Angeles|seatac tacoma
PDX|KPDX|Portland|Portland|US|America/Los_Angeles|oregon
ANC|PANC|Anchorage|Anchorage|US|America/Anchorage|alaska ted stevens
HNL|PHNL|Honolulu|Honolulu|US|Pacific/Honolulu|hawaii
SJU|TJSJ|San Juan|San Juan|PR|America/Puerto_Rico|puerto rico
YYZ|CYYZ|Toronto Pearson|Toronto|CA|America/Toronto|pearson
YTZ|CYTZ|Toronto Billy Bishop|Toronto|CA|America/Toronto|island
YUL|CYUL|Montréal-Trudeau|Montréal|CA|America/Toronto|montreal trudeau
YVR|CYVR|Vancouver|Vancouver|CA|America/Vancouver|
YYC|CYYC|Calgary|Calgary|CA|America/Edmonton|
YEG|CYEG|Edmonton|Edmonton|CA|America/Edmonton|
YOW|CYOW|Ottawa|Ottawa|CA|America/Toronto|macdonald-cartier
YHZ|CYHZ|Halifax|Halifax|CA|America/Halifax|stanfield
YWG|CYWG|Winnipeg|Winnipeg|CA|America/Winnipeg|
YQB|CYQB|Québec City|Québec|CA|America/Toronto|quebec jean lesage
YYT|CYYT|St. John's|St. John's|CA|America/St_Johns|newfoundland
MEX|MMMX|Mexico City|Mexico City|MX|America/Mexico_City|benito juarez
CUN|MMUN|Cancún|Cancún|MX|America/Cancun|
GDL|MMGL|Guadalajara|Guadalajara|MX|America/Mexico_City|
MTY|MMMY|Monterrey|Monterrey|MX|America/Monterrey|
SJD|MMSD|Los Cabos|San José del Cabo|MX|America/Mazatlan|cabo
PVR|MMPR|Puerto Vallarta|Puerto Vallarta|MX|America/Bahia_Banderas|
DXB|OMDB|Dubai|Dubai|AE|Asia/Dubai|
AUH|OMAA|Abu Dhabi|Abu Dhabi|AE|Asia/Dubai|
DOH|OTHH|Doha Hamad|Doha|QA|Asia/Qatar|hamad qatar
TLV|LLBG|Tel Aviv Ben Gurion|Tel Aviv|IL|Asia/Jerusalem|ben gurion
CAI|HECA|Cairo|Cairo|EG|Africa/Cairo|
CMN|GMMN|Casablanca|Casablanca|MA|Africa/Casablanca|mohammed v
RAK|GMMX|Marrakesh|Marrakesh|MA|Africa/Casablanca|marrakech menara
ADD|HAAB|Addis Ababa|Addis Ababa|ET|Africa/Addis_Ababa|bole
NBO|HKJK|Nairobi|Nairobi|KE|Africa/Nairobi|jomo kenyatta
JNB|FAOR|Johannesburg|Johannesburg|ZA|Africa/Johannesburg|o r tambo
CPT|FACT|Cape Town|Cape Town|ZA|Africa/Johannesburg|
DEL|VIDP|Delhi|Delhi|IN|Asia/Kolkata|indira gandhi new delhi
BOM|VABB|Mumbai|Mumbai|IN|Asia/Kolkata|bombay chhatrapati shivaji
SIN|WSSS|Singapore Changi|Singapore|SG|Asia/Singapore|changi
KUL|WMKK|Kuala Lumpur|Kuala Lumpur|MY|Asia/Kuala_Lumpur|
BKK|VTBS|Bangkok Suvarnabhumi|Bangkok|TH|Asia/Bangkok|suvarnabhumi
HKG|VHHH|Hong Kong|Hong Kong|HK|Asia/Hong_Kong|chek lap kok
TPE|RCTP|Taipei Taoyuan|Taipei|TW|Asia/Taipei|taoyuan
MNL|RPLL|Manila|Manila|PH|Asia/Manila|ninoy aquino
PVG|ZSPD|Shanghai Pudong|Shanghai|CN|Asia/Shanghai|pudong
PEK|ZBAA|Beijing Capital|Beijing|CN|Asia/Shanghai|
PKX|ZBAD|Beijing Daxing|Beijing|CN|Asia/Shanghai|daxing
ICN|RKSI|Seoul Incheon|Seoul|KR|Asia/Seoul|incheon
HND|RJTT|Tokyo Haneda|Tokyo|JP|Asia/Tokyo|haneda
NRT|RJAA|Tokyo Narita|Tokyo|JP|Asia/Tokyo|narita
SYD|YSSY|Sydney|Sydney|AU|Australia/Sydney|kingsford smith
MEL|YMML|Melbourne|Melbourne|AU|Australia/Melbourne|tullamarine
AKL|NZAA|Auckland|Auckland|NZ|Pacific/Auckland|
GRU|SBGR|São Paulo Guarulhos|São Paulo|BR|America/Sao_Paulo|guarulhos sao paulo
GIG|SBGL|Rio de Janeiro Galeão|Rio de Janeiro|BR|America/Sao_Paulo|galeao
EZE|SAEZ|Buenos Aires Ezeiza|Buenos Aires|AR|America/Argentina/Buenos_Aires|ezeiza
SCL|SCEL|Santiago de Chile|Santiago|CL|America/Santiago|arturo merino benitez chile
BOG|SKBO|Bogotá|Bogotá|CO|America/Bogota|el dorado
LIM|SPJC|Lima|Lima|PE|America/Lima|jorge chavez
PTY|MPTO|Panama City Tocumen|Panama City|PA|America/Panama|tocumen
`;

export type AirportRow = {
  iata: string;
  icao: string;
  name: string;
  city: string;
  country: string;
  tz: string;
  /** Lower-case, accent-folded words to match against. */
  words: string[];
  rank: number;
};

/** "Málaga" → "malaga"; punctuation becomes a space. */
export function fold(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export const AIRPORTS: AirportRow[] = TABLE.trim()
  .split("\n")
  .map((line, rank) => {
    const [iata, icao, name, city, country, tz, aliases = ""] = line.split("|");
    const words = [...new Set(fold(`${iata} ${icao} ${name} ${city} ${aliases}`).split(" ").filter(Boolean))];
    return { iata, icao, name, city, country, tz, words, rank };
  });

const BY_ICAO = new Map(AIRPORTS.map((a) => [a.icao, a]));
const BY_IATA = new Map(AIRPORTS.map((a) => [a.iata, a]));

export const airportByIcao = (icao: string | null | undefined) => (icao ? BY_ICAO.get(icao.trim().toUpperCase()) : undefined);
export const airportByIata = (iata: string | null | undefined) => (iata ? BY_IATA.get(iata.trim().toUpperCase()) : undefined);

/** "DUB · EIDW · Dublin". */
export const airportLabel = (a: Pick<AirportRow, "iata" | "icao" | "name">) => `${a.iata} · ${a.icao} · ${a.name}`;

/** What the field holds: a listed airport, or an ICAO code typed as is (the server decides if it knows it). */
export type AirportChoice = { icao: string; airport?: AirportRow };

export const choiceLabel = (c: AirportChoice) => (c.airport ? airportLabel(c.airport) : c.icao);

export const ICAO_SHAPE = /^[A-Z][A-Z0-9]{3}$/;

/** Shown before anything is typed: the hub and the places the demo goes. */
const SUGGESTED = ["EIDW", "EGLL", "LFPG", "EHAM", "EDDF", "KBOS", "KJFK", "KSFO"];
export const suggestedAirports = () => SUGGESTED.map((c) => BY_ICAO.get(c)).filter((a): a is AirportRow => !!a);

function score(a: AirportRow, q: string, code: string, terms: string[]): number {
  if (a.iata === code) return 100;
  if (a.icao === code) return 96;
  let s = 0;
  if (code.length === 3 && a.icao.startsWith(code)) s = 62;
  if (code.length < 3 && terms.length === 1 && a.iata.startsWith(code)) s = 58;
  if (fold(a.city) === q) s = Math.max(s, 80);
  if (terms.every((t) => a.words.some((w) => w.startsWith(t)))) {
    s = Math.max(s, terms.length > 1 ? 70 : a.words.includes(terms[0]) ? 66 : 52);
  } else if (q.length >= 3 && fold(a.name).includes(q)) {
    s = Math.max(s, 30);
  }
  return s;
}

/**
 * Rank airports for what was typed: exact IATA/ICAO first, then code prefixes, then city and name
 * words (accent-insensitive; every typed word must start some word of the airport).
 */
export function searchAirports(query: string, limit = 8): AirportRow[] {
  const q = fold(query);
  if (!q) return suggestedAirports().slice(0, limit);
  const code = q.replace(/\s+/g, "").toUpperCase();
  const terms = q.split(" ");
  return AIRPORTS.map((a) => ({ a, s: score(a, q, code, terms) }))
    .filter((x) => x.s > 0)
    .sort((x, y) => y.s - x.s || x.a.rank - y.a.rank)
    .slice(0, limit)
    .map((x) => x.a);
}

/**
 * Typed text → a choice without a click: an exact IATA or ICAO code, the label the field shows, one
 * clear match, or a well-formed ICAO code we don't list (the server answers for that one).
 */
export function resolveAirport(query: string): AirportChoice | null {
  const raw = query.trim();
  if (!raw) return null;
  const code = raw.toUpperCase();
  const byCode = airportByIata(code) ?? airportByIcao(code);
  if (byCode) return { icao: byCode.icao, airport: byCode };
  const labelled = code.match(/\b[A-Z][A-Z0-9]{3}\b/g)?.map((c) => airportByIcao(c)).find((a): a is AirportRow => !!a);
  if (labelled && code.includes("·")) return { icao: labelled.icao, airport: labelled };
  const hits = searchAirports(raw, 3);
  const q = fold(raw);
  if (hits.length === 1) return { icao: hits[0].icao, airport: hits[0] };
  if (hits.length > 1 && fold(hits[0].city) === q && fold(hits[1].city) !== q) return { icao: hits[0].icao, airport: hits[0] };
  if (!hits.length && ICAO_SHAPE.test(code)) return { icao: code };
  return null;
}
