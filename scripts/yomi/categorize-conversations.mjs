import { readFileSync, writeFileSync, renameSync } from 'node:fs';

const CONV = '/home/tony/CascadeProjects/chaba/stacks/web/public/apps/yomi/conversations.json';

const CATEGORIES = [
  { id: 'Family', keywords: ['ครอบครัว','บ้าน','พ่อ','แม่','ลูก','ปู่','ย่า','ตา','ยาย','น้อง','พี่','ที่บ้าน','แฟน','สามี','ภรรยา','family','dad','mom','parent','home'] },
  { id: 'Work', keywords: ['งาน','office','บริษัท','ทีม','project','ลูกค้า','การงาน','work','team','meeting','business','company','job','office','colleague'] },
  { id: 'Promo', keywords: ['ช้อป','shopping','sale','ลด','โปร','ดีล','ส่วนลด','คูปอง','พอยท์','7-eleven','big c','true','shopee','lazada','jd','promotion','promo','flash sale','free',' points','คะแนน','สินค้า','จำหน่าย','7-11','7 eleven'] },
  { id: 'Official', keywords: ['official','บริการ','ธนาคาร','รัฐ','ประกัน','คลินิก','โรงพยาบาล','hospital','bank','gov','service','clinic','สาขา','ออฟฟิศ','ร้าน','store','delivery','order','แจ้ง','เตือน','ระบบ'] },
  { id: 'Group', keywords: ['group','room','ห้อง','กลุ่ม','แชทกลุ่ม','group chat'] },
];

function normalize(str) {
  return String(str ?? '').toLowerCase().normalize('NFKC');
}
const BRANDS = new Set([
  'Big C TH','CP ALL 7-Eleven TH','LINE SHOPPING','ShopeeTH','True5G','TrueYou'
].map(normalize));

function categorize(c) {
  const text = normalize([c.name, c.lastPreview, c.summary].filter(Boolean).join(' '));
  const name = normalize(c.name);
  const isGroupLike = c.id.startsWith('c') || c.id.startsWith('r');

  if (BRANDS.has(name)) return { category: 'Official', source: 'brand' };

  for (const cat of CATEGORIES) {
    if (cat.id === 'Group' && !isGroupLike) continue;
    for (const kw of cat.keywords) {
      if (text.includes(kw.toLowerCase())) return { category: cat.id, source: 'text' };
    }
  }

  if (isGroupLike) return { category: 'Group', source: 'id' };
  return { category: 'Personal', source: 'default' };
}

function main() {
  const data = JSON.parse(readFileSync(CONV, 'utf8'));
  if (!Array.isArray(data.conversations)) throw new Error('conversations array missing');

  for (const c of data.conversations) {
    const isGroup = c.id.startsWith('c') || c.id.startsWith('r');
    const result = categorize(c);
    c.isGroup = isGroup;
    c.category = result.category;
    c.categorySource = result.source;
  }

  const tmp = CONV + '.tmp';
  writeFileSync(tmp, JSON.stringify(data, null, 2));
  renameSync(tmp, CONV);

  const counts = {};
  for (const c of data.conversations) counts[c.category] = (counts[c.category] || 0) + 1;
  console.log(`Categorized ${data.conversations.length} conversations in ${CONV}`);
  console.log(counts);
}

main();
