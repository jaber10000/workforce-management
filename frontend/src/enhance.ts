/* Design-only enhancements: EN/বাংলা translation, cursor glow, scroll progress.
   Pure DOM layer — no changes to pages, API or logic. Call initEnhance() once. */
type Lang = 'en' | 'bn'
const KEY = 'wf-lang'

const BN: Record<string, string> = {
  'Workforce': 'ওয়ার্কফোর্স', 'Roster': 'রোস্টার', 'Workspace': 'ওয়ার্কস্পেস', 'Search': 'খুঁজুন',
  'Dashboard': 'ড্যাশবোর্ড', 'Employees': 'কর্মী', 'Leaves': 'ছুটি', 'Leave': 'ছুটি', 'Swaps': 'শিফট বদল', 'Approvals': 'অনুমোদন',
  'Messages': 'বার্তা', 'Teams': 'টিম', 'Users': 'ব্যবহারকারী', 'Audit': 'অডিট', 'Import': 'ইমপোর্ট', 'KPI': 'কেপিআই', 'Chat': 'চ্যাট',
  'My home': 'আমার হোম', 'Team portal': 'টিম পোর্টাল',
  'Sign in': 'সাইন ইন', 'Signing in…': 'সাইন ইন হচ্ছে…', 'Sign out': 'সাইন আউট', 'Username': 'ইউজারনেম', 'Password': 'পাসওয়ার্ড',
  'Sign in with the account your administrator created.': 'অ্যাডমিনের তৈরি অ্যাকাউন্ট দিয়ে সাইন ইন করুন।', 'Login failed': 'লগইন ব্যর্থ হয়েছে',
  'Workforce operations': 'ওয়ার্কফোর্স অপারেশনস', 'Employee management': 'কর্মী ব্যবস্থাপনা', 'Export CSV': 'সিএসভি এক্সপোর্ট', 'Add employee': 'কর্মী যোগ করুন',
  'Employees shown': 'প্রদর্শিত কর্মী', 'Based on current filters': 'বর্তমান ফিল্টার অনুযায়ী', 'Active in view': 'দৃশ্যমান সক্রিয়', 'Eligible for roster planning': 'রোস্টার পরিকল্পনার যোগ্য',
  'Senior support': 'সিনিয়র সাপোর্ট', 'Within current results': 'বর্তমান ফলাফলের মধ্যে', 'Weekly off spread': 'সাপ্তাহিক অফ-ডে বিন্যাস', 'Shift eligibility': 'শিফটের যোগ্যতা',
  'People resting on each weekday. Uneven bars make roster gaps.': 'প্রতিদিন কারা অফ আছেন। অসম বার মানে রোস্টারে ফাঁক।', 'People who can be rostered on each shift.': 'প্রতিটি শিফটে যাদের রোস্টার করা যায়।',
  'Team directory': 'টিম ডিরেক্টরি', 'Search, sort and maintain employee records. Press / to search.': 'কর্মীর তথ্য খুঁজুন, সাজান ও হালনাগাদ করুন। খুঁজতে / চাপুন।',
  'Search by name, ID, phone or thana…': 'নাম, আইডি, ফোন বা থানা দিয়ে খুঁজুন…', 'Include inactive': 'নিষ্ক্রিয়সহ দেখান',
  'Edit': 'সম্পাদনা', 'Delete': 'মুছুন', 'Save': 'সংরক্ষণ', 'Cancel': 'বাতিল', 'Close': 'বন্ধ', 'Confirm': 'নিশ্চিত করুন', 'Submit': 'জমা দিন', 'Apply': 'প্রয়োগ', 'Reset': 'রিসেট', 'Refresh': 'রিফ্রেশ', 'Download': 'ডাউনলোড', 'Upload': 'আপলোড',
  'Approve': 'অনুমোদন', 'Reject': 'প্রত্যাখ্যান', 'Pending': 'অপেক্ষমাণ', 'Approved': 'অনুমোদিত', 'Rejected': 'প্রত্যাখ্যাত', 'Active': 'সক্রিয়', 'Inactive': 'নিষ্ক্রিয়',
  'Name': 'নাম', 'Role': 'ভূমিকা', 'Status': 'অবস্থা', 'Actions': 'কার্যক্রম', 'Phone': 'ফোন', 'Team': 'টিম', 'Date': 'তারিখ', 'Reason': 'কারণ', 'Type': 'ধরন', 'Shift': 'শিফট', 'Off day': 'অফ ডে', 'Off days': 'অফ ডে',
  'Morning': 'সকাল', 'Evening': 'বিকাল', 'Night': 'রাত', 'Senior': 'সিনিয়র', 'Manager': 'ম্যানেজার', 'Admin': 'অ্যাডমিন', 'Leader': 'লিডার', 'Team leader': 'টিম লিডার', 'Member': 'সদস্য',
  'Appearance': 'অ্যাপিয়ারেন্স', 'Mode': 'মোড', 'Colour theme': 'রঙের থিম', 'Light': 'লাইট', 'Dark': 'ডার্ক', 'System': 'সিস্টেম', 'Density': 'ঘনত্ব', 'Comfortable': 'স্বচ্ছন্দ', 'Compact': 'কমপ্যাক্ট', 'Motion': 'মোশন', 'Calm': 'শান্ত', 'Full': 'পূর্ণ',
  'Loading…': 'লোড হচ্ছে…', 'No results': 'কোনো ফলাফল নেই', 'No data': 'কোনো তথ্য নেই', 'Mon': 'সোম', 'Tue': 'মঙ্গল', 'Wed': 'বুধ', 'Thu': 'বৃহ', 'Fri': 'শুক্র', 'Sat': 'শনি', 'Sun': 'রবি',
  'Table': 'টেবিল', 'Cards': 'কার্ড', 'Export': 'এক্সপোর্ট', 'Filter': 'ফিল্টার', 'All': 'সব', 'Today': 'আজ', 'Week': 'সপ্তাহ', 'Month': 'মাস',
  'Phase 5 · Approval & production': 'ফেজ ৫ · অনুমোদন ও প্রোডাকশন',
}
const RULES: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^(\d+) records?$/, m => `${bd(m[1])}টি রেকর্ড`], [/^(\d+) unread$/, m => `${bd(m[1])}টি অপঠিত`],
  [/^Welcome back,?\s*(.+)$/, m => `স্বাগতম, ${m[1]}`], [/^(\d+) days?$/, m => `${bd(m[1])} দিন`],
]
const bd = (s: string) => s.replace(/\d/g, d => '০১২৩৪৫৬৭৮৯'[+d])
const norm = (s: string) => s.replace(/\s+/g, ' ').trim()

function tr(src: string, lang: Lang): string {
  if (lang === 'en') return src
  const t = norm(src); if (!t) return src
  let out = BN[t]
  if (!out) for (const [re, fn] of RULES) { const m = t.match(re); if (m) { out = fn(m); break } }
  return out ? src.replace(t, out) : src
}

let lang: Lang = (() => { try { return localStorage.getItem(KEY) === 'bn' ? 'bn' : 'en' } catch { return 'en' } })()
const textState = new WeakMap<Node, { src: string; out: string }>()
const ATTRS = ['placeholder', 'title', 'aria-label']
const attrState = new WeakMap<Element, Record<string, { src: string; out: string }>>()

function doText(n: Node) {
  const p = n.parentElement
  if (!p || ['SCRIPT', 'STYLE', 'TEXTAREA'].includes(p.tagName) || p.closest('[data-no-i18n]')) return
  const cur = n.nodeValue ?? '', st = textState.get(n)
  const src = st && st.out === cur ? st.src : cur       // React rewrote it → new original
  const out = tr(src, lang)
  if (out !== cur) n.nodeValue = out
  textState.set(n, { src, out })
}
function doAttrs(el: Element) {
  if (el.closest('[data-no-i18n]')) return
  const rec = attrState.get(el) ?? {}
  for (const a of ATTRS) {
    const cur = el.getAttribute(a); if (cur == null) continue
    const st = rec[a], src = st && st.out === cur ? st.src : cur, out = tr(src, lang)
    if (out !== cur) el.setAttribute(a, out)
    rec[a] = { src, out }
  }
  attrState.set(el, rec)
}
function walk(root: Node) {
  if (root.nodeType === 3) { doText(root); return }
  if (root.nodeType !== 1) return
  doAttrs(root as Element)
  const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT)
  for (let n = w.nextNode(); n; n = w.nextNode()) n.nodeType === 3 ? doText(n) : doAttrs(n as Element)
}

export function initEnhance() {
  const root = document.documentElement
  root.dataset.lang = lang; root.lang = lang
  const font = document.createElement('link')
  font.rel = 'stylesheet'; font.href = 'https://fonts.googleapis.com/css2?family=Hind+Siliguri:wght@400;500;600;700&display=swap'
  document.head.appendChild(font)

  const mo = new MutationObserver(recs => {
    mo.disconnect()
    for (const r of recs) {
      if (r.type === 'characterData') doText(r.target)
      else if (r.type === 'attributes') doAttrs(r.target as Element)
      else r.addedNodes.forEach(walk)
    }
    mo.observe(document.body, cfg)
  })
  const cfg: MutationObserverInit = { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ATTRS }
  const apply = () => { mo.disconnect(); walk(document.body); mo.observe(document.body, cfg) }

  // language button (outside React tree)
  const btn = document.createElement('button')
  btn.className = 'fx-lang'; btn.type = 'button'; btn.setAttribute('data-no-i18n', '')
  const paint = () => { btn.innerHTML = `<span class="fx-globe">🌐</span><span>${lang === 'en' ? '<b>EN</b> · বাংলা' : 'EN · <b>বাংলা</b>'}</span>`; btn.title = lang === 'en' ? 'Switch to বাংলা' : 'Switch to English' }
  btn.onclick = () => {
    lang = lang === 'en' ? 'bn' : 'en'
    try { localStorage.setItem(KEY, lang) } catch { /* ignore */ }
    root.dataset.lang = lang; root.lang = lang; paint(); apply()
  }
  paint(); document.body.appendChild(btn)

  // scroll progress
  const bar = document.createElement('div'); bar.className = 'fx-progress'; document.body.appendChild(bar)
  const onScroll = () => { const h = root.scrollHeight - innerHeight; bar.style.setProperty('--p', String(h > 0 ? Math.min(1, scrollY / h) : 0)) }
  addEventListener('scroll', onScroll, { passive: true }); onScroll()

  // cursor glow on cards
  addEventListener('pointermove', e => {
    const c = (e.target as Element | null)?.closest?.('.panel, .stat-card') as HTMLElement | null
    if (!c) return
    const r = c.getBoundingClientRect()
    c.style.setProperty('--mx', `${e.clientX - r.left}px`); c.style.setProperty('--my', `${e.clientY - r.top}px`)
  }, { passive: true })

  apply()
}
