const fs = require("fs");
const os = require("os");
const path = require("path");
const sharp = require("sharp");

const screenshotDir = path.resolve(__dirname, "../assets/screenshots");
const expected = [
  "01-login.png",
  "02-dashboard.png",
  "03-audit.png",
  "04-risk-review.png",
  "05-collaboration.png",
  "06-rectify.png",
  "07-reports.png",
  "08-knowledge.png",
  "09-admin.png",
  "10-reports-normal.png",
];

async function main() {
  const actual = fs.readdirSync(screenshotDir).filter((file) => file.endsWith(".png")).sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`screenshot set mismatch: ${actual.join(", ")}`);
  }

  const layers = [];
  for (const [index, file] of expected.entries()) {
    const filePath = path.join(screenshotDir, file);
    const image = sharp(filePath);
    const metadata = await image.metadata();
    const stats = await image.stats();
    const spread = Math.max(...stats.channels.map((channel) => channel.max - channel.min));
    const bytes = fs.statSync(filePath).size;
    if (metadata.width < 1600 || metadata.height < 900 || bytes < 10000 || spread < 40) {
      throw new Error(`invalid screenshot ${file}: ${metadata.width}x${metadata.height}, ${bytes} bytes, spread ${spread}`);
    }
    process.stdout.write(`verified ${file}: ${metadata.width}x${metadata.height}, ${bytes} bytes\n`);
    layers.push({
      input: await sharp(filePath)
        .resize(540, 340, { fit: "contain", background: "#F5F3EE" })
        .png()
        .toBuffer(),
      left: (index % 3) * 540,
      top: Math.floor(index / 3) * 340,
    });
  }

  const contactPath = path.join(os.tmpdir(), "contract-solution-screenshots-contact.png");
  await sharp({
    create: {
      width: 1620,
      height: Math.ceil(expected.length / 3) * 340,
      channels: 3,
      background: "#F5F3EE",
    },
  }).composite(layers).png().toFile(contactPath);
  process.stdout.write(`contact sheet ${contactPath}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
