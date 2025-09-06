const express = require('express');
const app = express();
app.use(express.json());

app.get('/health', (_, res) => res.json({ ok: true }));

app.post('/analyze', (req, res) => {
  const text = (req.body?.text || '').toString();
  const score = text.includes('!') ? 0.7 : 0.5; // примитивный намёк на “интенсивность”
  res.json({ sentiment: 'neutral', intensity: score, emotions: ['calm'] });
});

app.listen(5004, () => console.log('sentiment up on :5004'));
