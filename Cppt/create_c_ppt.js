const pptxgen = require("pptxgenjs");

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "C Language Guide";
pres.title = "C语言特性深度解析";

// ===== Color Palette (Teal Trust) =====
const C = {
  teal: "028090",
  seafoam: "00A896",
  mint: "02C39A",
  dark: "0D3B4F",
  white: "FFFFFF",
  lightBg: "F0FDFA",
  textDark: "0D3B4F",
  textLight: "E0F2F1",
  cardBg: "FFFFFF",
  muted: "6B8F9E",
  accentGold: "F59E0B",
  codeBg: "0D3B4F",
};

// ===== Helper: fresh shadow factory =====
const cardShadow = () => ({
  type: "outer",
  color: "000000",
  blur: 8,
  offset: 3,
  angle: 135,
  opacity: 0.1,
});

// ===== Slide 1: Title Slide =====
{
  const slide = pres.addSlide();
  slide.background = { color: C.dark };

  // Large decorative circle
  slide.addShape(pres.shapes.OVAL, {
    x: 6.0,
    y: -2.0,
    w: 6,
    h: 6,
    fill: { color: C.teal, transparency: 70 },
  });

  // Small accent circle
  slide.addShape(pres.shapes.OVAL, {
    x: 8.0,
    y: 3.5,
    w: 1.5,
    h: 1.5,
    fill: { color: C.mint, transparency: 60 },
  });

  // Bottom decorative bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0,
    y: 5.2,
    w: 10,
    h: 0.425,
    fill: { color: C.teal, transparency: 40 },
  });

  // Title
  slide.addText("C 语言特性深度解析", {
    x: 0.8,
    y: 1.0,
    w: 7,
    h: 1.2,
    fontSize: 42,
    fontFace: "Arial Black",
    color: C.textLight,
    bold: true,
    margin: 0,
  });

  // Subtitle
  slide.addText("从语法精髓到系统编程的底层力量", {
    x: 0.8,
    y: 2.3,
    w: 7,
    h: 0.6,
    fontSize: 18,
    fontFace: "Calibri",
    color: C.mint,
    margin: 0,
  });

  // Divider
  slide.addShape(pres.shapes.LINE, {
    x: 0.8,
    y: 3.1,
    w: 2,
    h: 0,
    line: { color: C.mint, width: 2.5 },
  });

  // Footer info
  slide.addText("5 页精华 · 核心特性全览", {
    x: 0.8,
    y: 4.4,
    w: 5,
    h: 0.4,
    fontSize: 13,
    fontFace: "Calibri",
    color: C.muted,
    margin: 0,
  });
}

// ===== Slide 2: 简洁语法与指针 =====
{
  const slide = pres.addSlide();
  slide.background = { color: C.lightBg };

  // Top accent bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0,
    y: 0,
    w: 10,
    h: 0.06,
    fill: { color: C.teal },
  });

  // Title
  slide.addText("简洁语法 · 指针威力", {
    x: 0.6,
    y: 0.3,
    w: 8,
    h: 0.7,
    fontSize: 28,
    fontFace: "Arial Black",
    color: C.textDark,
    bold: true,
    margin: 0,
  });

  slide.addShape(pres.shapes.LINE, {
    x: 0.6,
    y: 1.05,
    w: 1.5,
    h: 0,
    line: { color: C.teal, width: 2 },
  });

  // Left card: 简洁语法
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6,
    y: 1.4,
    w: 4.2,
    h: 3.5,
    fill: { color: C.cardBg },
    shadow: cardShadow(),
  });

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6,
    y: 1.4,
    w: 4.2,
    h: 0.06,
    fill: { color: C.teal },
  });

  slide.addText("精炼的语法体系", {
    x: 0.9,
    y: 1.6,
    w: 3.6,
    h: 0.5,
    fontSize: 18,
    fontFace: "Calibri",
    color: C.textDark,
    bold: true,
    margin: 0,
  });

  slide.addText([
    { text: "仅 32 个关键字，语法简洁优雅", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "过程式编程，函数为基本单元", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "丰富的运算符集（算术/逻辑/位）", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "预处理指令 #include / #define", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "头文件机制实现模块化开发", options: { bullet: true, fontSize: 13, color: "444444" } },
  ], {
    x: 0.9, y: 2.2, w: 3.6, h: 2.5,
    fontFace: "Calibri", valign: "top", margin: 0,
  });

  // Right card: 指针
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 5.2,
    y: 1.4,
    w: 4.2,
    h: 3.5,
    fill: { color: C.cardBg },
    shadow: cardShadow(),
  });

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 5.2,
    y: 1.4,
    w: 4.2,
    h: 0.06,
    fill: { color: C.seafoam },
  });

  slide.addText("指针 — C 的灵魂", {
    x: 5.5,
    y: 1.6,
    w: 3.6,
    h: 0.5,
    fontSize: 18,
    fontFace: "Calibri",
    color: C.textDark,
    bold: true,
    margin: 0,
  });

  slide.addText([
    { text: "直接操作内存地址，极致灵活", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "动态内存分配 malloc / free", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "指针运算与数组的紧密关联", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "函数指针实现回调机制", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "构建链表、树等数据结构的基础", options: { bullet: true, fontSize: 13, color: "444444" } },
  ], {
    x: 5.5, y: 2.2, w: 3.6, h: 2.5,
    fontFace: "Calibri", valign: "top", margin: 0,
  });

  // Bottom stat
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6,
    y: 5.05,
    w: 8.8,
    h: 0.4,
    fill: { color: C.teal },
  });
  slide.addText("\"指针让 C 语言兼具高级语言的表达力与汇编语言的操控力\"", {
    x: 0.6, y: 5.05, w: 8.8, h: 0.4,
    fontSize: 12, fontFace: "Calibri", color: C.textLight,
    align: "center", valign: "middle", italic: true, margin: 0,
  });
}

// ===== Slide 3: 内存管理三区域 =====
{
  const slide = pres.addSlide();
  slide.background = { color: C.dark };

  // Title
  slide.addText("精细的内存管理模型", {
    x: 0.6,
    y: 0.3,
    w: 8,
    h: 0.7,
    fontSize: 28,
    fontFace: "Arial Black",
    color: C.textLight,
    bold: true,
    margin: 0,
  });

  slide.addShape(pres.shapes.LINE, {
    x: 0.6,
    y: 1.05,
    w: 1.5,
    h: 0,
    line: { color: C.mint, width: 2 },
  });

  // Three cards
  const regions = [
    {
      title: "栈区 (Stack)",
      items: ["局部变量自动分配释放", "函数调用帧压栈出栈", "LIFO 后进先出", "速度快，容量有限"],
      accent: C.mint,
    },
    {
      title: "堆区 (Heap)",
      items: ["malloc / calloc 分配", "free 手动释放", "灵活但需防内存泄漏", "速度较慢，容量大"],
      accent: C.accentGold,
    },
    {
      title: "静态区 (Static)",
      items: ["全局/静态变量存储", "程序生命周期内存在", "默认初始化为 0", "作用域由 static 控制"],
      accent: "F87171",
    },
  ];

  const cardW = 2.7;
  const gap = 0.35;
  const startX = 0.6;
  const cardsY = 1.4;

  regions.forEach((r, i) => {
    const cx = startX + i * (cardW + gap);

    slide.addShape(pres.shapes.RECTANGLE, {
      x: cx, y: cardsY, w: cardW, h: 3.2,
      fill: { color: "1A3A4A" },
      shadow: cardShadow(),
    });

    slide.addShape(pres.shapes.RECTANGLE, {
      x: cx, y: cardsY, w: cardW, h: 0.06,
      fill: { color: r.accent },
    });

    slide.addText(r.title, {
      x: cx + 0.2, y: cardsY + 0.2, w: cardW - 0.4, h: 0.45,
      fontSize: 16, fontFace: "Calibri", color: r.accent, bold: true, margin: 0,
    });

    const bullets = r.items.map((item, idx) => ({
      text: item,
      options: { bullet: true, breakLine: idx < r.items.length - 1, fontSize: 12, color: C.textLight },
    }));

    slide.addText(bullets, {
      x: cx + 0.2, y: cardsY + 0.75, w: cardW - 0.4, h: 2.3,
      fontFace: "Calibri", valign: "top", margin: 0,
    });
  });

  // Bottom note
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 4.85, w: 8.8, h: 0.55,
    fill: { color: "0A2A3A" },
  });
  slide.addText("💡 手动内存管理是 C 的强大之处 —— 掌握它，你就真正理解了计算机", {
    x: 0.6, y: 4.85, w: 8.8, h: 0.55,
    fontSize: 12, fontFace: "Calibri", color: C.muted,
    align: "center", valign: "middle", margin: 0,
  });
}

// ===== Slide 4: 数据结构与标准库 =====
{
  const slide = pres.addSlide();
  slide.background = { color: C.lightBg };

  // Top accent bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06,
    fill: { color: C.teal },
  });

  // Title
  slide.addText("数据结构与标准库", {
    x: 0.6, y: 0.3, w: 8, h: 0.7,
    fontSize: 28, fontFace: "Arial Black", color: C.textDark, bold: true, margin: 0,
  });

  slide.addShape(pres.shapes.LINE, {
    x: 0.6, y: 1.05, w: 1.5, h: 0,
    line: { color: C.teal, width: 2 },
  });

  // Left: 数据结构
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 1.4, w: 4.2, h: 2.8,
    fill: { color: C.cardBg }, shadow: cardShadow(),
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 1.4, w: 4.2, h: 0.06,
    fill: { color: C.teal },
  });

  slide.addText("内置数据结构", {
    x: 0.9, y: 1.6, w: 3.6, h: 0.45,
    fontSize: 17, fontFace: "Calibri", color: C.textDark, bold: true, margin: 0,
  });

  slide.addText([
    { text: "数组", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444", bold: true } },
    { text: "  连续内存，随机访问 O(1)", options: { bullet: true, indentLevel: 1, breakLine: true, fontSize: 12, color: "666666" } },
    { text: "结构体 struct", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444", bold: true } },
    { text: "  自定义复合数据类型", options: { bullet: true, indentLevel: 1, breakLine: true, fontSize: 12, color: "666666" } },
    { text: "联合体 union", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444", bold: true } },
    { text: "  共享内存，节省空间", options: { bullet: true, indentLevel: 1, breakLine: true, fontSize: 12, color: "666666" } },
    { text: "枚举 enum", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444", bold: true } },
    { text: "  命名整型常量，增强可读性", options: { bullet: true, indentLevel: 1, fontSize: 12, color: "666666" } },
  ], {
    x: 0.9, y: 2.15, w: 3.6, h: 1.9,
    fontFace: "Calibri", valign: "top", margin: 0,
  });

  // Right: 标准库
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 5.2, y: 1.4, w: 4.2, h: 2.8,
    fill: { color: C.cardBg }, shadow: cardShadow(),
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 5.2, y: 1.4, w: 4.2, h: 0.06,
    fill: { color: C.seafoam },
  });

  slide.addText("标准库概览", {
    x: 5.5, y: 1.6, w: 3.6, h: 0.45,
    fontSize: 17, fontFace: "Calibri", color: C.textDark, bold: true, margin: 0,
  });

  slide.addText([
    { text: "<stdio.h>    输入输出函数", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "<stdlib.h>   内存管理 / 工具", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "<string.h>   字符串操作函数", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "<math.h>     数学运算库", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "<time.h>     日期与时间处理", options: { bullet: true, breakLine: true, fontSize: 13, color: "444444" } },
    { text: "<ctype.h>    字符分类与转换", options: { bullet: true, fontSize: 13, color: "444444" } },
  ], {
    x: 5.5, y: 2.15, w: 3.6, h: 1.9,
    fontFace: "Calibri", valign: "top", margin: 0,
  });

  // Bottom: Code snippet
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.6, y: 4.4, w: 8.8, h: 0.95,
    fill: { color: C.codeBg },
  });

  slide.addText([
    { text: "#include <stdio.h>", options: { breakLine: true, fontSize: 11, color: "81C784" } },
    { text: 'int main() { printf("Hello, C!\\n"); return 0; }', options: { fontSize: 11, color: C.textLight } },
  ], {
    x: 0.9, y: 4.45, w: 8.2, h: 0.85,
    fontFace: "Consolas", valign: "middle", margin: 0,
  });
}

// ===== Slide 5: 总结与展望 =====
{
  const slide = pres.addSlide();
  slide.background = { color: C.dark };

  // Decorative circles
  slide.addShape(pres.shapes.OVAL, {
    x: -1.5, y: 3, w: 4, h: 4,
    fill: { color: C.teal, transparency: 70 },
  });
  slide.addShape(pres.shapes.OVAL, {
    x: 7.5, y: -1, w: 3.5, h: 3.5,
    fill: { color: C.teal, transparency: 60 },
  });

  // Title
  slide.addText("总结与展望", {
    x: 0.8, y: 0.4, w: 8, h: 0.7,
    fontSize: 32, fontFace: "Arial Black", color: C.textLight, bold: true, margin: 0,
  });

  slide.addShape(pres.shapes.LINE, {
    x: 0.8, y: 1.15, w: 1.5, h: 0,
    line: { color: C.mint, width: 2.5 },
  });

  // Three key points
  const points = [
    { num: "01", title: "系统编程的基石", desc: "操作系统、嵌入式、驱动开发的首选语言" },
    { num: "02", title: "性能极致", desc: "零运行时开销，直接编译为高效机器码" },
    { num: "03", title: "永恒的价值", desc: "理解 C = 理解计算机的运行原理" },
  ];

  points.forEach((p, i) => {
    const ty = 1.6 + i * 1.1;

    slide.addShape(pres.shapes.OVAL, {
      x: 0.8, y: ty, w: 0.6, h: 0.6,
      fill: { color: C.mint },
    });
    slide.addText(p.num, {
      x: 0.8, y: ty, w: 0.6, h: 0.6,
      fontSize: 14, fontFace: "Calibri", color: C.dark,
      bold: true, align: "center", valign: "middle", margin: 0,
    });

    slide.addText(p.title, {
      x: 1.6, y: ty - 0.05, w: 4, h: 0.35,
      fontSize: 18, fontFace: "Calibri", color: C.textLight, bold: true, margin: 0,
    });

    slide.addText(p.desc, {
      x: 1.6, y: ty + 0.3, w: 6, h: 0.3,
      fontSize: 13, fontFace: "Calibri", color: C.muted, margin: 0,
    });
  });

  // Bottom bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.2, w: 10, h: 0.425,
    fill: { color: "0A2A3A" },
  });
  slide.addText("\"C 语言 —— 历久弥新，永不过时的系统编程语言\"", {
    x: 0.5, y: 5.2, w: 9, h: 0.425,
    fontSize: 13, fontFace: "Calibri", color: C.mint,
    align: "center", valign: "middle", italic: true, margin: 0,
  });
}

// ===== Write File =====
pres.writeFile({ fileName: "Cppt/C语言特性深度解析.pptx" })
  .then(() => console.log("✅ PPT created: Cppt/C语言特性深度解析.pptx"))
  .catch(err => console.error("❌ Error:", err));
