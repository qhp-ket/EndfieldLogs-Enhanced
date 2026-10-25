// Measure at unit window scale. Font/avatar multipliers remain independent.
(() => {
  const root = document.documentElement;
  let channel, pending, sent = '', scheduled = false;
  const canvas = document.createElement('canvas'), context = canvas.getContext('2d');
  function textWidth(node, text) {
    const style = getComputedStyle(node);
    context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    return context.measureText(text ?? node.textContent).width;
  }
  function publish(reference, reset) {
    pending = reference;
    window.endfieldOverlay?.setContentReference(reference);
    const signature = JSON.stringify(reference);
    if (channel && (signature !== sent || reset)) {
      channel.fitLayout(reference.width, reference.height, reference.style);
      sent = signature;
    }
  }
  if (window.qt?.webChannelTransport && window.QWebChannel) {
    new QWebChannel(qt.webChannelTransport, bridge => {
      channel = bridge.objects.comboContent;
      if (pending) publish(pending, true);
    });
  }
  window.fitComboContent = () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(async () => {
      await document.fonts.ready;
      scheduled = false;
      const config = window.endfieldOverlay?.config;
      const shell = document.querySelector('.combo-overlay-shell');
      const slots = [...document.querySelectorAll('.slot')];
      if (!config || !shell || slots.length !== 4) return;
      const font = Math.max(.5, Math.min(3, Number(config.fontScale) || 1));
      const changes = [[root, '--overlay-window-scale', '1'], [root, '--overlay-font-scale', String(font)]];
      const original = changes.map(([node, key]) => node.style.getPropertyValue(key));
      const oldWidth = shell.style.width;
      let reference;
      try {
        for (const [node, key, value] of changes) node.style.setProperty(key, value);
        const icon = slots[0].querySelector('.portrait').getBoundingClientRect().width;
        const names = slots.map(row => textWidth(row.querySelector('.name')));
        const name = Math.max(textWidth(slots[0].querySelector('.name'), '角色名称'), ...names);
        const value = Math.max(textWidth(slots[0].querySelector('.value'), '100% · ≈100.0s'),
          ...slots.map(row => textWidth(row.querySelector('.value'))));
        const circles = document.body.dataset.style === 'circles';
        const width = Math.ceil(circles
          ? 4*Math.max(icon+4, name, value)+40*font
          : Math.max(320, icon+name+value+42*font));
        shell.style.width = `${width}px`;
        reference = {width, height:Math.ceil(shell.getBoundingClientRect().height),
          style: document.body.dataset.style, scaleAxis: circles ? 'both' : 'height',
          font, avatar: config.settings?.avatar_size_percent || 100};
      } finally {
        shell.style.width = oldWidth;
        changes.forEach(([node, key], i) => original[i] ? node.style.setProperty(key, original[i]) : node.style.removeProperty(key));
      }
      const reset = !!config.fitReset;
      delete config.fitReset;
      publish(reference, reset);
    });
  };
})();
