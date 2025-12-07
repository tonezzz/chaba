const LANGUAGE_OPTIONS = [
  { value: 'th', label: 'ไทย (TH)', description: 'ค่าเริ่มต้น' },
  { value: 'en', label: 'English (EN)', description: 'Default' },
  { value: 'de', label: 'Deutsch (DE)', description: 'German' },
  { value: 'no', label: 'Norsk (NO)', description: 'Norwegian' },
  { value: 'sv', label: 'Svenska (SV)', description: 'Swedish' },
  { value: 'es', label: 'Español (ES)', description: 'Spanish' },
  { value: 'ja', label: '日本語 (JA)', description: 'Japanese' },
  { value: 'zh', label: '中文 (ZH)', description: 'Chinese' },
  { value: 'ko', label: '한국어 (KO)', description: 'Korean' }
];

const DEFAULT_LANGUAGE = 'th';

const UI_COPY = {
  default: {
    heroEyebrow: 'Surf Thailand • A1 Vision Utilities',
    heroTitle: 'Photo understanding sandbox',
    heroLede:
      'Drop in a still photo, choose one of the vision prompts, and we’ll send it through our Glama vision endpoint to describe the scene and pinpoint notable objects.',
    langLabel: 'Language',
    uploadHeading: '1. Upload photo',
    uploadBody: 'Single still image, max 10 MB. Works great with portrait or landscape shots.',
    dropTitle: 'Drag & drop photo',
    dropAlt: 'or',
    browseButton: 'browse files',
    cameraButton: 'take a photo',
    fileHintEmpty: 'No file selected yet.',
    promptHeading: '2. Pick a vision brief',
    promptBody: 'Tap a chip to autofill the prompt, or fine-tune in the text box.',
    modelLabel: 'Vision model',
    modelTagLabel: 'LLM',
    latencyLabel: 'Latency',
    promptLabel: 'Custom instructions',
    promptPlaceholder: 'Explain what you want the model to focus on…',
    analyzeButtonIdle: 'Run describe + detect',
    analyzeButtonBusy: 'Analyzing…',
    statusWaiting: 'Waiting for your photo…',
    statusPhotoReady: 'Photo ready. Pick a prompt to continue.',
    statusInvalidFile: 'Please select an image file (jpg, png, heic).',
    statusFileTooLarge: 'Image must be 10MB or less.',
    statusNeedPhoto: 'Please upload a photo first.',
    statusNeedPrompt: 'Prompt cannot be empty.',
    statusAnalyzing: 'Sending image to Glama…',
    statusAnalyzeComplete: 'Vision analysis complete.',
    statusAnalyzeFailed: 'Vision analysis failed.',
    summaryHeading: 'Vision summary',
    summaryEmpty: 'No analysis yet.',
    objectsHeading: 'Detected objects',
    objectsSubheading: 'Top items, sorted by model confidence.',
    objectsEmpty: 'No objects returned.',
    rawHeading: 'Raw payload',
    rawSubheading: 'Direct JSON from the Glama response.',
    rawPlaceholder: '// Awaiting response…',
    chatHeading: 'Ask about this analysis',
    chatSubheading: 'Once a photo is analyzed, ask follow-up questions here.',
    chatPlaceholder: 'Type a question in your language…',
    chatSendButton: 'Ask',
    chatUserLabel: 'You',
    chatAssistantLabel: 'Vision analyst',
    chatEmpty: 'Chat is ready as soon as you run an analysis.',
    chatThinking: 'Thinking…',
    chatError: 'Sorry, I couldn’t answer that.',
    statusNeedAnalysis: 'Run a describe + detect first, then start a chat.'
  },
  th: {
    heroEyebrow: 'เซิร์ฟไทยแลนด์ • ชุดเครื่องมือวิชั่น A1',
    heroTitle: 'สนามทดลองวิเคราะห์ภาพ',
    heroLede:
      'อัปโหลดภาพนิ่ง เลือกพรอมต์วิชั่น แล้วเราจะส่งไปยัง Glama เพื่อบรรยายฉากและเน้นวัตถุสำคัญให้คุณทันที',
    langLabel: 'ภาษา',
    uploadHeading: '1. อัปโหลดภาพ',
    uploadBody: 'รองรับภาพนิ่ง 1 ไฟล์ ขนาดไม่เกิน 10 MB จะเป็นแนวตั้งหรือแนวนอนก็ได้',
    dropTitle: 'ลาก & วางรูปภาพ',
    dropAlt: 'หรือ',
    browseButton: 'เลือกไฟล์',
    cameraButton: 'ถ่ายรูป',
    fileHintEmpty: 'ยังไม่ได้เลือกไฟล์',
    promptHeading: '2. เลือกโจทย์วิชั่น',
    promptBody: 'แตะชิปเพื่อกรอกพรอมต์อัตโนมัติ หรือปรับแต่งข้อความเอง',
    modelLabel: 'โมเดลวิชั่น',
    modelTagLabel: 'LLM',
    latencyLabel: 'ความหน่วง',
    promptLabel: 'คำสั่งเพิ่มเติม',
    promptPlaceholder: 'อธิบายสิ่งที่อยากให้โมเดลโฟกัส…',
    analyzeButtonIdle: 'สั่งวิเคราะห์ภาพ',
    analyzeButtonBusy: 'กำลังวิเคราะห์…',
    statusWaiting: 'รอรูปภาพจากคุณ…',
    statusPhotoReady: 'ไฟล์พร้อมแล้ว เลือกพรอมต์ต่อได้เลย',
    statusInvalidFile: 'กรุณาเลือกไฟล์ภาพ (jpg, png, heic)',
    statusFileTooLarge: 'ไฟล์ต้องไม่เกิน 10 MB',
    statusNeedPhoto: 'กรุณาอัปโหลดภาพก่อน',
    statusNeedPrompt: 'ห้ามปล่อยพรอมต์ว่าง',
    statusAnalyzing: 'กำลังส่งภาพไปยัง Glama…',
    statusAnalyzeComplete: 'วิเคราะห์ภาพเสร็จแล้ว',
    statusAnalyzeFailed: 'วิเคราะห์ภาพไม่สำเร็จ',
    summaryHeading: 'สรุปผลวิชั่น',
    summaryEmpty: 'ยังไม่มีการวิเคราะห์',
    objectsHeading: 'วัตถุที่ตรวจพบ',
    objectsSubheading: 'เรียงตามความมั่นใจของโมเดล',
    objectsEmpty: 'ไม่มีวัตถุที่รายงาน',
    rawHeading: 'ข้อมูลดิบ',
    rawSubheading: 'JSON ตรงจากการตอบกลับของ Glama',
    rawPlaceholder: '// รอผลลัพธ์…',
    chatHeading: 'ถามต่อเกี่ยวกับการวิเคราะห์นี้',
    chatSubheading: 'เมื่อประมวลผลภาพแล้ว พิมพ์คำถามติดตามได้ที่นี่',
    chatPlaceholder: 'พิมพ์คำถามเป็นภาษาของคุณ…',
    chatSendButton: 'ถาม',
    chatUserLabel: 'คุณ',
    chatAssistantLabel: 'นักวิเคราะห์',
    chatEmpty: 'พร้อมแชททันทีหลังสั่งวิเคราะห์',
    chatThinking: 'กำลังคิด…',
    chatError: 'ขออภัย ไม่สามารถตอบคำถามนี้ได้',
    statusNeedAnalysis: 'กรุณาสั่ง describe + detect ก่อนแล้วค่อยเริ่มแชท'
  },
  de: {
    heroEyebrow: 'Surf Thailand • A1 Vision-Werkzeuge',
    heroTitle: 'Sandbox für Bildverständnis',
    heroLede:
      'Lade ein Standbild hoch, wähle einen Vision-Prompt und wir schicken es über Glama, um die Szene zu beschreiben und Objekte hervorzuheben.',
    langLabel: 'Sprache',
    uploadHeading: '1. Foto hochladen',
    uploadBody: 'Ein einzelnes Bild, max. 10 MB. Funktioniert im Hoch- oder Querformat.',
    dropTitle: 'Foto ziehen & ablegen',
    dropAlt: 'oder',
    browseButton: 'Datei wählen',
    cameraButton: 'Foto aufnehmen',
    fileHintEmpty: 'Noch kein Foto ausgewählt.',
    promptHeading: '2. Vision-Brief wählen',
    promptBody: 'Tippe einen Chip an, um den Prompt zu füllen, oder passe den Text an.',
    modelLabel: 'Vision-Modell',
    modelTagLabel: 'LLM',
    latencyLabel: 'Latenz',
    promptLabel: 'Eigene Anweisungen',
    promptPlaceholder: 'Erkläre, worauf das Modell achten soll…',
    analyzeButtonIdle: 'Analyse starten',
    analyzeButtonBusy: 'Analysiere…',
    statusWaiting: 'Warte auf dein Foto…',
    statusPhotoReady: 'Foto bereit. Wähle einen Prompt.',
    statusInvalidFile: 'Bitte eine Bilddatei wählen (jpg, png, heic).',
    statusFileTooLarge: 'Bild muss 10 MB oder kleiner sein.',
    statusNeedPhoto: 'Bitte zuerst ein Foto hochladen.',
    statusNeedPrompt: 'Prompt darf nicht leer sein.',
    statusAnalyzing: 'Sende Bild an Glama…',
    statusAnalyzeComplete: 'Vision-Analyse abgeschlossen.',
    statusAnalyzeFailed: 'Vision-Analyse fehlgeschlagen.',
    summaryHeading: 'Vision-Zusammenfassung',
    summaryEmpty: 'Noch keine Analyse.',
    objectsHeading: 'Erkannte Objekte',
    objectsSubheading: 'Top-Ergebnisse nach Modellvertrauen sortiert.',
    objectsEmpty: 'Keine Objekte geliefert.',
    rawHeading: 'Rohdaten',
    rawSubheading: 'Direktes JSON aus der Glama-Antwort.',
    rawPlaceholder: '// Warte auf Ergebnis…',
    chatHeading: 'Fragen zur Analyse',
    chatSubheading: 'Nach der Fotoanalyse kannst du hier Rückfragen stellen.',
    chatPlaceholder: 'Stelle deine Frage in deiner Sprache…',
    chatSendButton: 'Fragen',
    chatUserLabel: 'Du',
    chatAssistantLabel: 'Vision-Analyst',
    chatEmpty: 'Starte zuerst eine Analyse, dann ist der Chat bereit.',
    chatThinking: 'Denke nach…',
    chatError: 'Sorry, ich konnte das nicht beantworten.',
    statusNeedAnalysis: 'Führe zuerst describe + detect aus und starte dann den Chat.'
  },
  no: {
    heroEyebrow: 'Surf Thailand • A1 Visionverktøy',
    heroTitle: 'Sandkasse for bildeforståelse',
    heroLede:
      'Last opp et stillbilde, velg en visjonsprompt, så sender vi det via Glama for å beskrive scenen og finne objekter.',
    langLabel: 'Språk',
    uploadHeading: '1. Last opp bilde',
    uploadBody: 'Ett stillbilde, maks 10 MB. Fungerer i stående eller liggende format.',
    dropTitle: 'Dra og slipp bilde',
    dropAlt: 'eller',
    browseButton: 'velg filer',
    cameraButton: 'ta et bilde',
    fileHintEmpty: 'Ingen fil valgt ennå.',
    promptHeading: '2. Velg en visjonsbrief',
    promptBody: 'Trykk på en chip for å fylle prompten, eller finjuster teksten.',
    modelLabel: 'Visjonsmodell',
    modelTagLabel: 'LLM',
    latencyLabel: 'Latens',
    promptLabel: 'Egne instruksjoner',
    promptPlaceholder: 'Forklar hva modellen skal fokusere på…',
    analyzeButtonIdle: 'Kjør beskriv + detekter',
    analyzeButtonBusy: 'Analyserer…',
    statusWaiting: 'Venter på bildet ditt…',
    statusPhotoReady: 'Bilde klart. Velg en prompt.',
    statusInvalidFile: 'Velg en bildefil (jpg, png, heic).',
    statusFileTooLarge: 'Bildet må være 10 MB eller mindre.',
    statusNeedPhoto: 'Last opp et bilde først.',
    statusNeedPrompt: 'Prompt kan ikke være tom.',
    statusAnalyzing: 'Sender bilde til Glama…',
    statusAnalyzeComplete: 'Visjonsanalyse fullført.',
    statusAnalyzeFailed: 'Visjonsanalyse feilet.',
    summaryHeading: 'Visjonsoppsummering',
    summaryEmpty: 'Ingen analyse ennå.',
    objectsHeading: 'Oppdagede objekter',
    objectsSubheading: 'Viktigste funn sortert på modellens trygghet.',
    objectsEmpty: 'Ingen objekter returnert.',
    rawHeading: 'Rådata',
    rawSubheading: 'JSON direkte fra Glama-responsen.',
    rawPlaceholder: '// Venter på svar…',
    chatHeading: 'Still spørsmål om analysen',
    chatSubheading: 'Når bildet er analysert kan du stille oppfølgingsspørsmål her.',
    chatPlaceholder: 'Skriv et spørsmål på ditt språk…',
    chatSendButton: 'Spør',
    chatUserLabel: 'Du',
    chatAssistantLabel: 'Visjonsanalytiker',
    chatEmpty: 'Kjør en analyse først, så er chatten klar.',
    chatThinking: 'Tenker…',
    chatError: 'Jeg klarte ikke å svare på det.',
    statusNeedAnalysis: 'Kjør beskriv + detekter før du starter chatten.'
  },
  sv: {
    heroEyebrow: 'Surf Thailand • A1 Visionverktyg',
    heroTitle: 'Sandlåda för bildförståelse',
    heroLede:
      'Ladda upp ett stillfoto, välj en visionbrief så skickar vi det via Glama för att beskriva scenen och hitta objekt.',
    langLabel: 'Språk',
    uploadHeading: '1. Ladda upp foto',
    uploadBody: 'Ett stillbild, max 10 MB. Funkar i stående eller liggande läge.',
    dropTitle: 'Dra & släpp foto',
    dropAlt: 'eller',
    browseButton: 'bläddra filer',
    cameraButton: 'ta ett foto',
    fileHintEmpty: 'Ingen fil vald ännu.',
    promptHeading: '2. Välj en visionbrief',
    promptBody: 'Tryck på en chip för att fylla prompten eller finjustera texten.',
    modelLabel: 'Visionmodell',
    modelTagLabel: 'LLM',
    latencyLabel: 'Latens',
    promptLabel: 'Egna instruktioner',
    promptPlaceholder: 'Berätta vad modellen ska fokusera på…',
    analyzeButtonIdle: 'Kör beskriv + detektera',
    analyzeButtonBusy: 'Analyserar…',
    statusWaiting: 'Väntar på ditt foto…',
    statusPhotoReady: 'Foto klart. Välj en prompt.',
    statusInvalidFile: 'Välj en bildfil (jpg, png, heic).',
    statusFileTooLarge: 'Bilden måste vara 10 MB eller mindre.',
    statusNeedPhoto: 'Ladda upp ett foto först.',
    statusNeedPrompt: 'Prompten får inte vara tom.',
    statusAnalyzing: 'Skickar bilden till Glama…',
    statusAnalyzeComplete: 'Visionanalysen är klar.',
    statusAnalyzeFailed: 'Visionanalysen misslyckades.',
    summaryHeading: 'Visionssammanfattning',
    summaryEmpty: 'Ingen analys ännu.',
    objectsHeading: 'Upptäckta objekt',
    objectsSubheading: 'Toppobjekt sorterade efter modellens säkerhet.',
    objectsEmpty: 'Inga objekt returnerades.',
    rawHeading: 'Råpayload',
    rawSubheading: 'JSON direkt från Glama-svaret.',
    rawPlaceholder: '// Väntar på svar…',
    chatHeading: 'Fråga om analysen',
    chatSubheading: 'När bilden är analyserad kan du ställa följdfrågor här.',
    chatPlaceholder: 'Skriv en fråga på ditt språk…',
    chatSendButton: 'Fråga',
    chatUserLabel: 'Du',
    chatAssistantLabel: 'Visionanalytiker',
    chatEmpty: 'Kör en analys först så aktiveras chatten.',
    chatThinking: 'Tänker…',
    chatError: 'Tyvärr kunde jag inte svara på det.',
    statusNeedAnalysis: 'Kör beskriv + detektera innan du använder chatten.'
  },
  es: {
    heroEyebrow: 'Surf Tailandia • Utilidades A1 Vision',
    heroTitle: 'Laboratorio de comprensión visual',
    heroLede:
      'Sube una foto fija, elige un prompt de visión y la enviaremos por Glama para describir la escena y señalar objetos clave.',
    langLabel: 'Idioma',
    uploadHeading: '1. Subir foto',
    uploadBody: 'Imagen fija única, máximo 10 MB. Funciona en vertical u horizontal.',
    dropTitle: 'Arrastra y suelta la foto',
    dropAlt: 'o',
    browseButton: 'explorar archivos',
    cameraButton: 'tomar una foto',
    fileHintEmpty: 'Aún no hay archivo seleccionado.',
    promptHeading: '2. Elige un brief de visión',
    promptBody: 'Toca un chip para autocompletar el prompt o ajusta el texto manualmente.',
    modelLabel: 'Modelo de visión',
    modelTagLabel: 'LLM',
    latencyLabel: 'Latencia',
    promptLabel: 'Instrucciones personalizadas',
    promptPlaceholder: 'Explica en qué debe enfocarse el modelo…',
    analyzeButtonIdle: 'Ejecutar describir + detectar',
    analyzeButtonBusy: 'Analizando…',
    statusWaiting: 'Esperando tu foto…',
    statusPhotoReady: 'Foto lista. Elige un prompt.',
    statusInvalidFile: 'Selecciona un archivo de imagen (jpg, png, heic).',
    statusFileTooLarge: 'La imagen debe pesar 10 MB o menos.',
    statusNeedPhoto: 'Primero sube una foto.',
    statusNeedPrompt: 'El prompt no puede estar vacío.',
    statusAnalyzing: 'Enviando imagen a Glama…',
    statusAnalyzeComplete: 'Análisis de visión completo.',
    statusAnalyzeFailed: 'El análisis de visión falló.',
    summaryHeading: 'Resumen de visión',
    summaryEmpty: 'Aún no hay análisis.',
    objectsHeading: 'Objetos detectados',
    objectsSubheading: 'Elementos principales ordenados por confianza del modelo.',
    objectsEmpty: 'No se devolvieron objetos.',
    rawHeading: 'Datos sin procesar',
    rawSubheading: 'JSON directo de la respuesta de Glama.',
    rawPlaceholder: '// Esperando respuesta…',
    chatHeading: 'Pregunta sobre la detección',
    chatSubheading: 'Cuando la foto esté analizada, haz tus preguntas de seguimiento aquí.',
    chatPlaceholder: 'Escribe tu pregunta en tu idioma…',
    chatSendButton: 'Preguntar',
    chatUserLabel: 'Tú',
    chatAssistantLabel: 'Analista de visión',
    chatEmpty: 'Ejecuta un análisis primero para habilitar el chat.',
    chatThinking: 'Pensando…',
    chatError: 'No pude responder eso.',
    statusNeedAnalysis: 'Ejecuta describir + detectar antes de iniciar el chat.'
  },
  ja: {
    heroEyebrow: 'Surf Thailand • A1 ビジョンツール',
    heroTitle: '画像理解サンドボックス',
    heroLede:
      '静止画をアップロードし、ビジョンプロンプトを選ぶだけで、Glama がシーンを説明し注目すべき物体を示します。',
    langLabel: '言語',
    uploadHeading: '1. 写真をアップロード',
    uploadBody: '静止画 1 枚、最大 10 MB。縦横どちらの写真でもOKです。',
    dropTitle: 'ドラッグ＆ドロップ',
    dropAlt: 'または',
    browseButton: 'ファイルを選択',
    cameraButton: '写真を撮る',
    fileHintEmpty: 'まだファイルが選択されていません。',
    promptHeading: '2. ビジョンブリーフを選択',
    promptBody: 'チップを押してプロンプトを自動入力するか、テキストを調整してください。',
    modelLabel: 'ビジョンモデル',
    modelTagLabel: 'LLM',
    latencyLabel: 'レイテンシ',
    promptLabel: 'カスタム指示',
    promptPlaceholder: 'モデルに注目してほしい点を説明してください…',
    analyzeButtonIdle: '解析を実行',
    analyzeButtonBusy: '解析中…',
    statusWaiting: '写真を待っています…',
    statusPhotoReady: '写真を受信しました。プロンプトを選択してください。',
    statusInvalidFile: '画像ファイル（jpg, png, heic）を選んでください。',
    statusFileTooLarge: '画像は 10 MB 以下にしてください。',
    statusNeedPhoto: 'まず写真をアップロードしてください。',
    statusNeedPrompt: 'プロンプトを空にすることはできません。',
    statusAnalyzing: 'Glama に送信しています…',
    statusAnalyzeComplete: 'ビジョン解析が完了しました。',
    statusAnalyzeFailed: 'ビジョン解析に失敗しました。',
    summaryHeading: 'ビジョンサマリー',
    summaryEmpty: 'まだ解析がありません。',
    objectsHeading: '検出されたオブジェクト',
    objectsSubheading: 'モデルの信頼度で並べた上位アイテム。',
    objectsEmpty: 'オブジェクトは返されませんでした。',
    rawHeading: '生データ',
    rawSubheading: 'Glama 応答の JSON をそのまま表示します。',
    rawPlaceholder: '// 結果を待機中…',
    chatHeading: 'この解析について質問する',
    chatSubheading: '写真を解析した後は、ここで追質問ができます。',
    chatPlaceholder: 'あなたの言語で質問を入力してください…',
    chatSendButton: '質問する',
    chatUserLabel: 'あなた',
    chatAssistantLabel: 'ビジョンアナリスト',
    chatEmpty: 'まず解析を実行するとチャットが利用できます。',
    chatThinking: '考えています…',
    chatError: '申し訳ありません、回答できませんでした。',
    statusNeedAnalysis: '先に describe + detect を実行してからチャットを始めてください。'
  },
  zh: {
    heroEyebrow: 'Surf Thailand • A1 视觉工具',
    heroTitle: '图像理解沙盒',
    heroLede:
      '上传一张静态照片，选择一个视觉提示，我们会通过 Glama 视觉接口描述场景并标记重点物体。',
    langLabel: '语言',
    uploadHeading: '1. 上传照片',
    uploadBody: '仅限单张静态图片，最大 10 MB，竖屏横屏都支持。',
    dropTitle: '拖拽上传照片',
    dropAlt: '或',
    browseButton: '浏览文件',
    cameraButton: '拍摄照片',
    fileHintEmpty: '尚未选择文件。',
    promptHeading: '2. 选择视觉任务',
    promptBody: '点击芯片自动填充提示，也可以在输入框中微调。',
    modelLabel: '视觉模型',
    modelTagLabel: 'LLM',
    latencyLabel: '延迟',
    promptLabel: '自定义指令',
    promptPlaceholder: '说明你希望模型关注的内容…',
    analyzeButtonIdle: '执行描述 + 检测',
    analyzeButtonBusy: '分析中…',
    statusWaiting: '等待你的照片…',
    statusPhotoReady: '照片就绪，继续选择提示。',
    statusInvalidFile: '请选择图片文件（jpg、png、heic）。',
    statusFileTooLarge: '图片必须小于或等于 10 MB。',
    statusNeedPhoto: '请先上传照片。',
    statusNeedPrompt: '提示不能为空。',
    statusAnalyzing: '正在将图片发送到 Glama…',
    statusAnalyzeComplete: '视觉分析完成。',
    statusAnalyzeFailed: '视觉分析失败。',
    summaryHeading: '视觉摘要',
    summaryEmpty: '尚无分析结果。',
    objectsHeading: '检测到的物体',
    objectsSubheading: '按模型置信度排序的重点项目。',
    objectsEmpty: '未返回任何物体。',
    rawHeading: '原始数据',
    rawSubheading: '来自 Glama 响应的 JSON。',
    rawPlaceholder: '// 正在等待响应…',
    chatHeading: '就本次分析提问',
    chatSubheading: '照片分析完成后，可在此提出追问。',
    chatPlaceholder: '用你的语言输入问题…',
    chatSendButton: '提问',
    chatUserLabel: '你',
    chatAssistantLabel: '视觉分析师',
    chatEmpty: '先运行一次分析即可启用聊天。',
    chatThinking: '思考中…',
    chatError: '抱歉，无法回答该问题。',
    statusNeedAnalysis: '请先执行描述+检测，再开始聊天。'
  },
  ko: {
    heroEyebrow: 'Surf Thailand • A1 비전 도구',
    heroTitle: '이미지 이해 샌드박스',
    heroLede:
      '정지 사진을 업로드하고 비전 프롬프트를 선택하면 Glama 엔드포인트가 장면을 설명하고 주요 객체를 표시합니다.',
    langLabel: '언어',
    uploadHeading: '1. 사진 업로드',
    uploadBody: '정지 이미지 1장, 최대 10 MB. 세로·가로 모두 지원.',
    dropTitle: '사진 끌어다 놓기',
    dropAlt: '또는',
    browseButton: '파일 찾아보기',
    cameraButton: '사진 찍기',
    fileHintEmpty: '아직 파일이 선택되지 않았습니다.',
    promptHeading: '2. 비전 브리프 선택',
    promptBody: '칩을 눌러 프롬프트를 자동 입력하거나 직접 수정하세요.',
    modelLabel: '비전 모델',
    modelTagLabel: 'LLM',
    latencyLabel: '지연 시간',
    promptLabel: '사용자 지정 지시',
    promptPlaceholder: '모델이 집중하길 원하는 내용을 설명하세요…',
    analyzeButtonIdle: '설명 + 감지 실행',
    analyzeButtonBusy: '분석 중…',
    statusWaiting: '사진을 기다리는 중…',
    statusPhotoReady: '사진 준비 완료. 프롬프트를 선택하세요.',
    statusInvalidFile: '이미지 파일을 선택하세요 (jpg, png, heic).',
    statusFileTooLarge: '이미지는 10 MB 이하여야 합니다.',
    statusNeedPhoto: '먼저 사진을 업로드하세요.',
    statusNeedPrompt: '프롬프트는 비워둘 수 없습니다.',
    statusAnalyzing: '이미지를 Glama로 전송 중…',
    statusAnalyzeComplete: '비전 분석이 완료되었습니다.',
    statusAnalyzeFailed: '비전 분석에 실패했습니다.',
    summaryHeading: '비전 요약',
    summaryEmpty: '아직 분석이 없습니다.',
    objectsHeading: '감지된 객체',
    objectsSubheading: '모델 신뢰도로 정렬된 주요 항목.',
    objectsEmpty: '반환된 객체가 없습니다.',
    rawHeading: '원시 페이로드',
    rawSubheading: 'Glama 응답의 JSON.',
    rawPlaceholder: '// 응답을 기다리는 중…',
    chatHeading: '분석 결과에 대해 질문하기',
    chatSubheading: '사진 분석이 끝나면 여기에서 후속 질문을 해보세요.',
    chatPlaceholder: '원하는 언어로 질문을 입력하세요…',
    chatSendButton: '질문',
    chatUserLabel: '사용자',
    chatAssistantLabel: '비전 분석가',
    chatEmpty: '먼저 분석을 실행하면 채팅을 사용할 수 있습니다.',
    chatThinking: '생각 중…',
    chatError: '죄송합니다. 답변할 수 없었습니다.',
    statusNeedAnalysis: '채팅을 시작하기 전에 describe + detect를 먼저 실행하세요.'
  }
};

const handleChatSubmit = async (event) => {
  event.preventDefault();
  if (!state.analysisContext) {
    setStatus('statusNeedAnalysis', 'error');
    return;
  }
  const question = elements.chatInput?.value?.trim();
  if (!question) {
    return;
  }

  appendChatMessage('user', question);
  pushChatHistory({ role: 'user', content: question });
  if (elements.chatInput) elements.chatInput.value = '';

  const thinkingText = t('chatThinking') || 'Thinking…';
  const pendingMessage = appendChatMessage('assistant', thinkingText, { pending: true });
  setChatBusy(true);

  try {
    const response = await fetch('/test/detects/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        question,
        description: state.analysisContext.description,
        objects: state.analysisContext.objects,
        language: state.language,
        history: state.chatHistory
      })
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || 'chat_failed');
    }
    const data = await response.json();
    const reply = (data?.reply || '').trim();
    if (pendingMessage) {
      pendingMessage.classList.remove('pending');
      const body = pendingMessage.querySelector('.chat-body');
      if (body) body.textContent = reply || t('chatError');
    }
    if (reply) {
      pushChatHistory({ role: 'assistant', content: reply });
    }
  } catch (error) {
    console.error('Chat failed', error);
    if (pendingMessage) {
      pendingMessage.classList.remove('pending');
      const body = pendingMessage.querySelector('.chat-body');
      if (body) body.textContent = t('chatError');
    }
  } finally {
    setChatBusy(false);
  }
};

const PROMPT_COPY = {
  default: [
    {
      id: 'urban',
      label: 'Street operations sweep',
      text: 'Describe traffic flow, signage status, crowd behavior, and note outages or hazards along the street.'
    },
    {
      id: 'retail',
      label: 'Retail fixture compliance',
      text: 'Audit shelf facings, promotional displays, and staff/customer interactions that affect merchandising discipline.'
    },
    {
      id: 'safety',
      label: 'Safety compliance sweep',
      text: 'Scan for PPE usage, blocked exits, spills, or anything that could violate safety protocols.'
    },
    {
      id: 'vehicle',
      label: 'Vehicle damage survey',
      text: 'Inspect exterior panels, glass, and lights; flag dents, scratches, rust, missing parts, and capture license info.'
    },
    {
      id: 'receipt',
      label: 'Receipt & slip extraction',
      text: 'Transcribe totals, taxes, store info, payment method, and any handwritten notes shown on the slip.'
    },
    {
      id: 'manual',
      label: 'Manual / SOP comprehension',
      text: 'Summarize the document purpose, key steps, warnings, and tools that are mentioned.'
    },
    {
      id: 'specsheet',
      label: 'Technical spec highlight',
      text: 'List model numbers, critical specs (power, dimensions, materials), certifications, and tolerances from the sheet.'
    }
  ],
  th: [
    {
      id: 'urban',
      label: 'สำรวจการปฏิบัติงานบนถนน',
      text: 'อธิบายการจราจร สถานะป้าย พฤติกรรมฝูงชน และแจ้งไฟดับหรือจุดเสี่ยงตลอดเส้นทาง'
    },
    {
      id: 'retail',
      label: 'ตรวจมาตรฐานหน้าร้าน',
      text: 'ตรวจการจัดเรียงสินค้า ป้ายโปรโมชัน และการปฏิสัมพันธ์พนักงาน/ลูกค้าที่มีผลต่อการขาย'
    },
    {
      id: 'safety',
      label: 'กวาดความปลอดภัย',
      text: 'ดูการใช้ PPE ทางหนีไฟที่ถูกปิด คราบหก หรือสิ่งที่ผิดข้อกำหนดความปลอดภัย'
    },
    {
      id: 'vehicle',
      label: 'ตรวจสภาพรถ',
      text: 'สำรวจตัวถัง กระจก และไฟ แจ้งรอยบุบ ขีดข่วน สนิม อะไหล่ที่หาย และข้อมูลป้ายทะเบียน'
    },
    {
      id: 'receipt',
      label: 'ถอดข้อมูลใบเสร็จ/สลิป',
      text: 'ถอดยอดรวม ภาษี ข้อมูลร้าน ช่องทางจ่าย และโน้ตที่เขียนด้วยมือบนสลิป'
    },
    {
      id: 'manual',
      label: 'สรุปคู่มือ/SOP',
      text: 'สรุปวัตถุประสงค์ ขั้นตอนสำคัญ คำเตือน และเครื่องมือที่กล่าวถึงในเอกสาร'
    },
    {
      id: 'specsheet',
      label: 'ดึงไฮไลต์สเปกเทคนิค',
      text: 'ระบุรุ่น ค่าสเปกหลัก (พลังงาน ขนาด วัสดุ) ใบรับรอง และค่าความคลาดเคลื่อนบนเอกสาร'
    }
  ],
  de: [
    {
      id: 'urban',
      label: 'Straßenbetrieb-Check',
      text: 'Beschreibe Verkehrsfluss, Beschilderung, Menschenverhalten und markiere Ausfälle oder Gefahren entlang der Straße.'
    },
    {
      id: 'retail',
      label: 'Retail-Compliance-Prüfung',
      text: 'Prüfe Regalflächen, Promotion-Displays sowie Personal- und Kundeninteraktionen, die das Merchandising beeinflussen.'
    },
    {
      id: 'safety',
      label: 'Sicherheits-Rundgang',
      text: 'Achte auf PSA, blockierte Ausgänge, Verschüttungen oder andere Verstöße gegen Sicherheitsregeln.'
    },
    {
      id: 'vehicle',
      label: 'Fahrzeugschadensbericht',
      text: 'Untersuche Karosserie, Glas und Beleuchtung; melde Dellen, Kratzer, Rost oder fehlende Teile plus Kennzeichen.'
    },
    {
      id: 'receipt',
      label: 'Beleg- & Bon-Erfassung',
      text: 'Schreibe Summen, Steuern, Filialdaten, Zahlungsart und handschriftliche Notizen aus dem Beleg heraus.'
    },
    {
      id: 'manual',
      label: 'Handbuch/SOP-Zusammenfassung',
      text: 'Fasse Zweck, wichtigste Schritte, Warnhinweise und erwähnte Werkzeuge des Dokuments zusammen.'
    },
    {
      id: 'specsheet',
      label: 'Technisches Datenblatt',
      text: 'Liste Modellnummern, Kerndaten (Leistung, Maße, Materialien), Zertifizierungen und Toleranzen vom Blatt auf.'
    }
  ],
  no: [
    {
      id: 'urban',
      label: 'Gateoperasjons-sveip',
      text: 'Beskriv trafikkflyt, skilting, publikumsatferd og pek ut avbrudd eller farer langs gaten.'
    },
    {
      id: 'retail',
      label: 'Butikkcompliance',
      text: 'Gå gjennom hyllefronter, kampanjemateriell og ansatte/kunde-interaksjoner som påvirker gjennomføringen.'
    },
    {
      id: 'safety',
      label: 'Sikkerhetsrunde',
      text: 'Se etter PPE-bruk, blokkerte utganger, søl eller andre brudd på sikkerhetsprosedyrer.'
    },
    {
      id: 'vehicle',
      label: 'Kjøretøyskade-rapport',
      text: 'Inspiser karosseri, glass og lys; noter bulker, riper, rust eller manglende deler samt skiltinformasjon.'
    },
    {
      id: 'receipt',
      label: 'Kvitteringsuttrekk',
      text: 'Les av totaler, avgifter, butikkinfo, betalingsmåte og eventuelle håndskrevne notater.'
    },
    {
      id: 'manual',
      label: 'Manual / SOP-oppsummering',
      text: 'Oppsummer dokumentets formål, nøkkeltrinn, advarsler og verktøy som nevnes.'
    },
    {
      id: 'specsheet',
      label: 'Teknisk spes-oversikt',
      text: 'List modellnumre, hovedspesifikasjoner (effekt, dimensjoner, materialer), sertifiseringer og toleranser.'
    }
  ],
  sv: [
    {
      id: 'urban',
      label: 'Gatuoperationer',
      text: 'Beskriv trafikflöde, skyltstatus, folks beteende och peka ut avbrott eller risker längs gatan.'
    },
    {
      id: 'retail',
      label: 'Butiksregelefterlevnad',
      text: 'Gå igenom hyllfronter, kampanjdisplayar och personal/kund‑interaktioner som påverkar merchandising.'
    },
    {
      id: 'safety',
      label: 'Säkerhetsrond',
      text: 'Notera PPE, blockerade utgångar, spill eller annat som bryter mot säkerhetsrutiner.'
    },
    {
      id: 'vehicle',
      label: 'Fordonsskaderapport',
      text: 'Inspektera kaross, glas och lampor; flagga bucklor, repor, rost eller saknade delar samt registreringsinfo.'
    },
    {
      id: 'receipt',
      label: 'Kvitto-/sliputdrag',
      text: 'Transkribera totalsummor, moms, butiksdata, betalningsmetod och handskrivna anteckningar.'
    },
    {
      id: 'manual',
      label: 'Manual/SOP-sammanfattning',
      text: 'Sammanfatta syfte, viktiga steg, varningar och verktyg som nämns i dokumentet.'
    },
    {
      id: 'specsheet',
      label: 'Teknisk spec-highlight',
      text: 'Lista modellnummer, nyckelspecar (effekt, mått, material), certifieringar och toleranser.'
    }
  ],
  es: [
    {
      id: 'urban',
      label: 'Barrido de operaciones urbanas',
      text: 'Describe el flujo vehicular, estado de señalización, comportamiento de la multitud y destaca cortes o riesgos en la calle.'
    },
    {
      id: 'retail',
      label: 'Cumplimiento en tienda',
      text: 'Audita frentes de góndola, exhibiciones promocionales e interacciones personal-cliente que afectan la ejecución comercial.'
    },
    {
      id: 'safety',
      label: 'Ronda de seguridad',
      text: 'Busca uso de EPP, salidas bloqueadas, derrames u otros elementos que violen protocolos de seguridad.'
    },
    {
      id: 'vehicle',
      label: 'Informe de daños vehiculares',
      text: 'Inspecciona carrocería, cristales y luces; marca golpes, rayones, óxido o piezas faltantes e incluye la placa.'
    },
    {
      id: 'receipt',
      label: 'Extracción de recibos/slips',
      text: 'Transcribe totales, impuestos, datos de la tienda, forma de pago y cualquier nota escrita a mano.'
    },
    {
      id: 'manual',
      label: 'Resumen de manual/SOP',
      text: 'Resume el propósito del documento, pasos clave, advertencias y herramientas mencionadas.'
    },
    {
      id: 'specsheet',
      label: 'Resumen de ficha técnica',
      text: 'Enumera números de modelo, especificaciones clave (potencia, dimensiones, materiales), certificaciones y tolerancias.'
    }
  ],
  ja: [
    {
      id: 'urban',
      label: '路上オペレーション点検',
      text: '交通の流れ、標識の状態、人の動きを説明し、停電や危険箇所を指摘してください。'
    },
    {
      id: 'retail',
      label: '店舗コンプライアンス確認',
      text: '棚割り、販促ディスプレイ、スタッフと顧客のやり取りを監査し、販売オペを評価します。'
    },
    {
      id: 'safety',
      label: '安全ラウンド',
      text: 'PPEの着用、塞がれた出口、こぼれやその他の安全違反を探してください。'
    },
    {
      id: 'vehicle',
      label: '車両ダメージ調査',
      text: '外装パネル、ガラス、ライトを確認し、へこみ・傷・錆・欠品とナンバー情報を報告してください。'
    },
    {
      id: 'receipt',
      label: 'レシート/伝票抽出',
      text: '合計、税額、店舗情報、支払方法、手書きメモを読み取ってください。'
    },
    {
      id: 'manual',
      label: 'マニュアル/SOP要約',
      text: '文書の目的、主要手順、警告、記載された工具を要約してください。'
    },
    {
      id: 'specsheet',
      label: '技術仕様ハイライト',
      text: '型番、主要スペック（出力・寸法・素材）、認証、許容差を列挙してください。'
    }
  ],
  zh: [
    {
      id: 'urban',
      label: '街道运行巡查',
      text: '描述车流、标志状态、人群行为，并标记道路上的停电或隐患。'
    },
    {
      id: 'retail',
      label: '门店合规检查',
      text: '审核货架陈列、促销展示以及员工与顾客互动，对执行情况进行评估。'
    },
    {
      id: 'safety',
      label: '安全巡检',
      text: '查看PPE佩戴、被阻挡的出口、溢漏或其它违反安全规程的情况。'
    },
    {
      id: 'vehicle',
      label: '车辆损伤报告',
      text: '检查车身、玻璃与灯具；标记凹陷、划痕、锈蚀或缺失零件，并记录车牌信息。'
    },
    {
      id: 'receipt',
      label: '收据/票据提取',
      text: '转写总额、税费、门店信息、付款方式及任何手写备注。'
    },
    {
      id: 'manual',
      label: '手册/SOP 摘要',
      text: '概述文档目的、关键步骤、警示语和提到的工具。'
    },
    {
      id: 'specsheet',
      label: '技术规格亮点',
      text: '列出型号、关键参数（功率、尺寸、材料）、认证以及公差。'
    }
  ],
  ko: [
    {
      id: 'urban',
      label: '도로 운영 점검',
      text: '교통 흐름, 표지 상태, 군중 행동을 설명하고 거리의 정전이나 위험 요소를 표시하세요.'
    },
    {
      id: 'retail',
      label: '매장 컴플라이언스 검사',
      text: '진열 상태, 프로모션 디스플레이, 직원·고객 상호작용을 점검해 매장 실행력을 평가하세요.'
    },
    {
      id: 'safety',
      label: '안전 순찰',
      text: 'PPE 착용, 막힌 비상구, 유출 등 안전 규정 위반을 찾아주세요.'
    },
    {
      id: 'vehicle',
      label: '차량 손상 조사',
      text: '차체, 유리, 조명을 살펴보고 찌그러짐, 흠집, 녹, 누락된 부품과 번호판 정보를 보고하세요.'
    },
    {
      id: 'receipt',
      label: '영수증/전표 추출',
      text: '총액, 세금, 매장 정보, 결제 수단, 손글씨 메모를 전사하세요.'
    },
    {
      id: 'manual',
      label: '매뉴얼/SOP 요약',
      text: '문서 목적, 핵심 단계, 경고, 언급된 도구를 요약하세요.'
    },
    {
      id: 'specsheet',
      label: '기술 사양 하이라이트',
      text: '모델 번호, 주요 사양(전력, 치수, 소재), 인증 및 허용오차를 나열하세요.'
    }
  ]
};
PROMPT_COPY.en = PROMPT_COPY.default;

const elements = {
  detectForm: document.getElementById('detectForm'),
  browseBtn: document.getElementById('browseBtn'),
  cameraBtn: document.getElementById('cameraBtn'),
  photoInput: document.getElementById('photoInput'),
  cameraInput: document.getElementById('cameraInput'),
  dropzone: document.querySelector('[data-dropzone]'),
  fileHint: document.getElementById('fileHint'),
  previewWrap: document.getElementById('previewWrap'),
  previewImage: document.getElementById('previewImage'),
  promptChips: document.getElementById('promptChips'),
  promptInput: document.getElementById('promptInput'),
  statusBanner: document.getElementById('statusBanner'),
  analyzeBtn: document.getElementById('analyzeBtn'),
  descriptionOutput: document.getElementById('descriptionOutput'),
  objectsGrid: document.getElementById('objectsGrid'),
  rawOutput: document.getElementById('rawOutput'),
  modelTag: document.getElementById('modelTag'),
  latencyTag: document.getElementById('latencyTag'),
  heroEyebrow: document.getElementById('heroEyebrow'),
  heroTitle: document.getElementById('heroTitle'),
  heroLede: document.getElementById('heroLede'),
  langLabel: document.getElementById('langLabel'),
  uploadHeading: document.getElementById('uploadHeading'),
  uploadBody: document.getElementById('uploadBody'),
  dropTitle: document.getElementById('dropTitle'),
  dropAlt: document.getElementById('dropAlt'),
  promptHeading: document.getElementById('promptHeading'),
  promptBody: document.getElementById('promptBody'),
  promptLabel: document.getElementById('promptLabel'),
  summaryHeading: document.getElementById('summaryHeading'),
  objectsHeading: document.getElementById('objectsHeading'),
  objectsSubheading: document.getElementById('objectsSubheading'),
  rawHeading: document.getElementById('rawHeading'),
  rawSubheading: document.getElementById('rawSubheading'),
  chatHeading: document.getElementById('chatHeading'),
  chatSubheading: document.getElementById('chatSubheading'),
  chatLog: document.getElementById('chatLog'),
  chatForm: document.getElementById('chatForm'),
  chatInput: document.getElementById('chatInput'),
  chatSendBtn: document.getElementById('chatSendBtn'),
  languageSelect: document.getElementById('languageSelect')
};

const state = {
  language: DEFAULT_LANGUAGE,
  promptSamples: [],
  selectedPromptId: null,
  selectedFile: null,
  isAnalyzing: false,
  hasAnalysis: false,
  hasRaw: false,
  hasObjects: false,
  statusKey: 'statusWaiting',
  statusState: '',
  statusOverride: null,
  analysisContext: null,
  chatHistory: [],
  isChatting: false
};

let promptInputDirty = false;

const updateChatAvailability = () => {
  const canChat = Boolean(state.analysisContext) && !state.isChatting;
  if (elements.chatInput) elements.chatInput.disabled = !canChat;
  if (elements.chatSendBtn) elements.chatSendBtn.disabled = !canChat;
};

const pushChatHistory = (entry) => {
  if (!entry || typeof entry !== 'object') return;
  const role = entry.role;
  const content = typeof entry.content === 'string' ? entry.content.trim() : '';
  if (!role || !content) return;
  state.chatHistory.push({ role, content });
  if (state.chatHistory.length > 8) {
    state.chatHistory = state.chatHistory.slice(-8);
  }
};

const getChatLabels = () => ({
  user: t('chatUserLabel') || 'You',
  assistant: t('chatAssistantLabel') || 'Vision analyst'
});

const showChatPlaceholder = () => {
  if (!elements.chatLog) return;
  elements.chatLog.innerHTML = '';
  const placeholder = document.createElement('p');
  placeholder.className = 'chat-empty';
  placeholder.textContent = t('chatEmpty');
  elements.chatLog.appendChild(placeholder);
};

const clearChatPlaceholder = () => {
  if (!elements.chatLog) return;
  elements.chatLog.querySelectorAll('.chat-empty').forEach((node) => node.remove());
};

const resetChatConversation = () => {
  state.chatHistory = [];
  state.isChatting = false;
  if (elements.chatInput) elements.chatInput.value = '';
  updateChatAvailability();
  showChatPlaceholder();
};

const clearChatContext = () => {
  state.analysisContext = null;
  resetChatConversation();
  updateChatAvailability();
};

const setChatBusy = (busy) => {
  state.isChatting = busy;
  updateChatAvailability();
};

const appendChatMessage = (role, content, { pending = false } = {}) => {
  if (!elements.chatLog) return null;
  clearChatPlaceholder();
  const message = document.createElement('div');
  message.className = `chat-message ${role}`;
  if (pending) message.classList.add('pending');
  const label = document.createElement('span');
  label.className = 'chat-label';
  const labels = getChatLabels();
  label.textContent = role === 'user' ? labels.user : labels.assistant;
  const body = document.createElement('p');
  body.className = 'chat-body';
  body.textContent = content;
  message.append(label, body);
  elements.chatLog.appendChild(message);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
  return message;
};

const refreshChatLocale = () => {
  if (!elements.chatLog) return;
  if (!state.chatHistory.length && !state.isChatting) {
    showChatPlaceholder();
    return;
  }
  const labels = getChatLabels();
  elements.chatLog.querySelectorAll('.chat-message.user .chat-label').forEach((label) => {
    label.textContent = labels.user;
  });
  elements.chatLog.querySelectorAll('.chat-message.assistant .chat-label').forEach((label) => {
    label.textContent = labels.assistant;
  });
};

const getStrings = (lang = state.language) => ({
  ...UI_COPY.default,
  ...(UI_COPY[lang] || {})
});

const t = (key, fallback = '') => {
  if (!key) return fallback;
  const strings = getStrings();
  return strings[key] ?? fallback ?? key;
};

const getPromptSet = () => PROMPT_COPY[state.language] || PROMPT_COPY.default;

const setStatus = (key, stateClass = '', overrideText) => {
  state.statusKey = key || 'statusWaiting';
  state.statusState = stateClass || '';
  state.statusOverride = overrideText ?? null;

  const text = overrideText || t(state.statusKey);
  if (!elements.statusBanner) return;
  elements.statusBanner.textContent = text;
  elements.statusBanner.classList.remove('ok', 'error');
  if (state.statusState === 'ok') elements.statusBanner.classList.add('ok');
  if (state.statusState === 'error') elements.statusBanner.classList.add('error');
};

const refreshStatus = () => setStatus(state.statusKey, state.statusState, state.statusOverride);

const setLoading = (loading) => {
  state.isAnalyzing = loading;
  if (!elements.analyzeBtn) return;
  elements.analyzeBtn.disabled = loading;
  elements.analyzeBtn.textContent = loading ? t('analyzeButtonBusy') : t('analyzeButtonIdle');
};

const resetOutputs = () => {
  state.hasAnalysis = false;
  state.hasRaw = false;
  state.hasObjects = false;
  clearChatContext();
  if (elements.descriptionOutput) elements.descriptionOutput.textContent = t('summaryEmpty');
  if (elements.rawOutput) elements.rawOutput.textContent = t('rawPlaceholder');
  if (elements.objectsGrid) {
    elements.objectsGrid.innerHTML = '';
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = t('objectsEmpty');
    elements.objectsGrid.appendChild(empty);
  }
  if (elements.modelTag) elements.modelTag.textContent = '—';
  if (elements.latencyTag) elements.latencyTag.textContent = '—';
};

const updateFileState = (file) => {
  state.selectedFile = file || null;
  if (!file) {
    if (elements.fileHint) elements.fileHint.textContent = t('fileHintEmpty');
    if (elements.previewWrap) elements.previewWrap.classList.add('hidden');
    if (elements.previewImage) elements.previewImage.src = '';
    resetOutputs();
    return;
  }
  clearChatContext();

  if (elements.fileHint) {
    const sizeMb = (file.size / 1024 / 1024).toFixed(2);
    elements.fileHint.textContent = `${file.name} · ${sizeMb} MB`;
  }
  const reader = new FileReader();
  reader.onload = (event) => {
    if (elements.previewImage) elements.previewImage.src = event.target.result;
    if (elements.previewWrap) elements.previewWrap.classList.remove('hidden');
  };
  reader.readAsDataURL(file);
};

const renderObjects = (objects = []) => {
  if (!elements.objectsGrid) return;
  elements.objectsGrid.innerHTML = '';
  if (!objects.length) {
    const empty = document.createElement('p');
    empty.className = 'muted';
    empty.textContent = t('objectsEmpty');
    elements.objectsGrid.appendChild(empty);
    state.hasObjects = false;
    return;
  }
  state.hasObjects = true;
  objects
    .slice()
    .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
    .forEach((obj) => {
      const pill = document.createElement('div');
      pill.className = 'object-pill';
      const label = document.createElement('h3');
      label.textContent = obj.label || 'Unknown object';
      const meta = document.createElement('p');
      const conf = typeof obj.confidence === 'number' ? `${(obj.confidence * 100).toFixed(1)}%` : '—';
      const detail = obj.detail ? ` • ${obj.detail}` : '';
      meta.textContent = `Confidence ${conf}${detail}`;
      pill.append(label, meta);
      elements.objectsGrid.appendChild(pill);
    });
};

const renderPromptChips = () => {
  if (!elements.promptChips) return;
  elements.promptChips.innerHTML = '';
  state.promptSamples = getPromptSet();
  state.promptSamples.forEach((sample) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.dataset.promptId = sample.id;
    chip.textContent = sample.label;
    chip.addEventListener('click', () => selectPrompt(sample.id, true));
    elements.promptChips.appendChild(chip);
  });
  const fallbackId = state.promptSamples[0]?.id;
  if (fallbackId) {
    selectPrompt(fallbackId, false);
  }
};

const selectPrompt = (promptId, userInitiated = false) => {
  const sample = state.promptSamples.find((entry) => entry.id === promptId);
  if (!sample) return;
  state.selectedPromptId = sample.id;
  if (!promptInputDirty || userInitiated) {
    if (elements.promptInput) elements.promptInput.value = sample.text;
    promptInputDirty = false;
  }
  if (elements.promptChips) {
    elements.promptChips.querySelectorAll('.chip').forEach((chip) => {
      chip.classList.toggle('active', chip.dataset.promptId === sample.id);
    });
  }
};

const handleFiles = (files) => {
  if (!files?.length) {
    updateFileState(null);
    setStatus('statusWaiting');
    return;
  }
  const file = files[0];
  if (!file.type.startsWith('image/')) {
    setStatus('statusInvalidFile', 'error');
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    setStatus('statusFileTooLarge', 'error');
    return;
  }
  updateFileState(file);
  setStatus('statusPhotoReady');
};

const bindDropzone = () => {
  if (!elements.dropzone) return;
  const prevent = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((eventName) => {
    elements.dropzone.addEventListener(eventName, prevent);
  });
  elements.dropzone.addEventListener('dragenter', () => elements.dropzone.classList.add('drag-over'));
  elements.dropzone.addEventListener('dragover', () => elements.dropzone.classList.add('drag-over'));
  elements.dropzone.addEventListener('dragleave', () => elements.dropzone.classList.remove('drag-over'));
  elements.dropzone.addEventListener('drop', (event) => {
    elements.dropzone.classList.remove('drag-over');
    handleFiles(event.dataTransfer.files);
  });
  elements.dropzone.addEventListener('click', () => elements.photoInput?.click());
};

const handleSubmit = async (event) => {
  event.preventDefault();
  if (!state.selectedFile) {
    setStatus('statusNeedPhoto', 'error');
    return;
  }
  const prompt = elements.promptInput?.value?.trim();
  if (!prompt) {
    setStatus('statusNeedPrompt', 'error');
    return;
  }

  const formData = new FormData();
  formData.append('photo', state.selectedFile, state.selectedFile.name);
  formData.append('prompt', prompt);

  setStatus('statusAnalyzing');
  setLoading(true);

  try {
    const response = await fetch('/test/detects/api/analyze', {
      method: 'POST',
      body: formData
    });
    if (!response.ok) {
      const detail = await response.text();
      throw new Error(detail || 'Vision analyze failed');
    }
    const result = await response.json();
    state.hasAnalysis = true;
    state.hasRaw = true;
    if (elements.descriptionOutput) {
      elements.descriptionOutput.textContent = result.description || t('summaryEmpty');
    }
    renderObjects(result.objects || []);
    if (elements.rawOutput) {
      elements.rawOutput.textContent = JSON.stringify(result.raw ?? result, null, 2);
    }
    if (elements.modelTag) {
      elements.modelTag.textContent = result.model || '—';
    }
    if (elements.latencyTag) {
      elements.latencyTag.textContent = result.latencyMs ? `${result.latencyMs} ms` : '—';
    }
    state.analysisContext = {
      description: result.description || '',
      objects: Array.isArray(result.objects) ? result.objects : []
    };
    resetChatConversation();
    setStatus('statusAnalyzeComplete', 'ok');
  } catch (error) {
    console.error('Analyze failed', error);
    const detail = error?.message && error.message !== 'Vision analyze failed' ? error.message : null;
    setStatus('statusAnalyzeFailed', 'error', detail || undefined);
  } finally {
    setLoading(false);
  }
};

const applyLocaleToUI = () => {
  const pairs = [
    [elements.heroEyebrow, 'heroEyebrow'],
    [elements.rawHeading, 'rawHeading'],
    [elements.rawSubheading, 'rawSubheading'],
    [elements.chatHeading, 'chatHeading'],
    [elements.chatSubheading, 'chatSubheading']
  ];
  pairs.forEach(([el, key]) => {
    if (el) el.textContent = t(key);
  });
  if (elements.dropAlt) elements.dropAlt.textContent = t('dropAlt');
  if (elements.browseBtn) elements.browseBtn.textContent = t('browseButton');
  if (elements.cameraBtn) elements.cameraBtn.textContent = t('cameraButton');
  if (elements.promptInput) elements.promptInput.placeholder = t('promptPlaceholder');
  if (elements.chatInput) elements.chatInput.placeholder = t('chatPlaceholder');
  if (elements.chatSendBtn) elements.chatSendBtn.textContent = t('chatSendButton');
  if (!state.selectedFile && elements.fileHint) elements.fileHint.textContent = t('fileHintEmpty');
  if (!state.hasAnalysis && elements.descriptionOutput) elements.descriptionOutput.textContent = t('summaryEmpty');
  if (!state.hasRaw && elements.rawOutput) elements.rawOutput.textContent = t('rawPlaceholder');
  if (!state.hasObjects) renderObjects([]);
  setLoading(state.isAnalyzing);
  refreshChatLocale();
};

const populateLanguageSelect = () => {
  if (!elements.languageSelect) return;
  elements.languageSelect.innerHTML = '';
  LANGUAGE_OPTIONS.forEach((opt) => {
    const option = document.createElement('option');
    option.value = opt.value;
    option.textContent = `${opt.label} — ${opt.description}`;
    if (opt.value === state.language) option.selected = true;
    elements.languageSelect.appendChild(option);
  });
};

const setLanguage = (lang) => {
  const exists = LANGUAGE_OPTIONS.some((entry) => entry.value === lang);
  state.language = exists ? lang : DEFAULT_LANGUAGE;
  document.documentElement.lang = state.language;
  try {
    localStorage.setItem('detectsLanguage', state.language);
  } catch {
    /* ignore */
  }
  promptInputDirty = false;
  state.selectedPromptId = null;
  populateLanguageSelect();
  renderPromptChips();
  applyLocaleToUI();
  refreshStatus();
};

const initLanguageSwitcher = () => {
  if (!elements.languageSelect) return;
  elements.languageSelect.addEventListener('change', (event) => {
    setLanguage(event.target.value);
  });
};

const init = () => {
  bindDropzone();
  elements.browseBtn?.addEventListener('click', () => elements.photoInput?.click());
  elements.photoInput?.addEventListener('change', (event) => handleFiles(event.target.files));
  elements.cameraBtn?.addEventListener('click', () => elements.cameraInput?.click());
  elements.cameraInput?.addEventListener('change', (event) => handleFiles(event.target.files));
  elements.detectForm?.addEventListener('submit', handleSubmit);
  elements.promptInput?.addEventListener('input', () => {
    promptInputDirty = true;
  });

  const stored = (() => {
    try {
      return localStorage.getItem('detectsLanguage');
    } catch {
      return null;
    }
  })();
  setLanguage(stored || DEFAULT_LANGUAGE);
  setStatus('statusWaiting');
  initLanguageSwitcher();
  showChatPlaceholder();
};

init();
