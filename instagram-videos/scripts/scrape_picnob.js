/**
 * Browser-side Picnob profile scraper.
 * Use via cursor-ide-browser MCP: Runtime.evaluate with awaitPromise=true.
 *
 * Wrap expression:
 *   (async () => { ...scrapePicnobProfile body... })()
 */

async function scrapePicnobProfile() {
  let lastCount = 0;
  let stableIterations = 0;
  for (let i = 0; i < 60; i++) {
    window.scrollTo(0, document.body.scrollHeight);
    await new Promise((r) => setTimeout(r, 1500));
    const c = document.querySelectorAll(".post_box").length;
    if (c === lastCount) {
      stableIterations++;
      if (stableIterations >= 3) break;
    } else {
      stableIterations = 0;
    }
    lastCount = c;
  }

  const posts = [];
  document.querySelectorAll(".post_box").forEach((box, idx) => {
    const a = box.querySelector('a[href*="/post/"]');
    const m = a?.href?.match(/\/post\/([^/?#]+)/);
    const counts = Array.from(box.querySelectorAll(".num")).map((e) =>
      e.textContent.trim()
    );
    posts.push({
      idx,
      pId: m?.[1] || null,
      caption: box.querySelector(".sum")?.textContent?.trim() || "",
      time: box.querySelector(".time")?.textContent?.trim() || "",
      likes: counts[0] || null,
      comments: counts[1] || null,
      downloadUrl: box.querySelector(".downbtn")?.href || null,
      thumbUrl:
        box.querySelector("img")?.dataset?.src ||
        box.querySelector("img")?.src ||
        null,
      isVideo: !!box.querySelector(".icon_video, [class*=video]"),
      isSidecar: !!box.querySelector(
        ".icon_album, [class*=sidecar], [class*=album]"
      ),
      picnobHref: a?.href || null,
    });
  });
  return posts;
}
