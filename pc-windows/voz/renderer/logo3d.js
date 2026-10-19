var scene, camera, renderer, particleSystem, coreMesh;
var currentState = 'idle';

window.init3DLogo = function() {
  var container = document.getElementById('canvas-container');
  if (!container) return;

  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(60, 1, 0.1, 1000);
  camera.position.z = 180;

  renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(600, 600);
  renderer.setPixelRatio(window.devicePixelRatio || 1);
  container.appendChild(renderer.domElement);

  var particleCount = 2000;
  var geometry = new THREE.BufferGeometry();
  var positions = new Float32Array(particleCount * 3);
  var colors = new Float32Array(particleCount * 3);
  var baseColor = new THREE.Color('#00f3ff');

  for (var i = 0; i < particleCount; i++) {
    var u = Math.random();
    var v = Math.random();
    var theta = u * 2.0 * Math.PI;
    var phi = Math.acos(2.0 * v - 1.0);
    var r = 60 + (Math.random() - 0.5) * 15;

    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    positions[i * 3 + 2] = r * Math.cos(phi);

    colors[i * 3] = baseColor.r;
    colors[i * 3 + 1] = baseColor.g;
    colors[i * 3 + 2] = baseColor.b;
  }

  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

  var material = new THREE.PointsMaterial({
    size: 2.2,
    vertexColors: true,
    transparent: true,
    opacity: 0.85,
    blending: THREE.AdditiveBlending
  });

  particleSystem = new THREE.Points(geometry, material);
  scene.add(particleSystem);

  var coreGeo = new THREE.IcosahedronGeometry(35, 2);
  var coreMat = new THREE.MeshBasicMaterial({
    color: '#00f3ff',
    wireframe: true,
    transparent: true,
    opacity: 0.4
  });
  coreMesh = new THREE.Mesh(coreGeo, coreMat);
  scene.add(coreMesh);

  animate();
};

function animate() {
  requestAnimationFrame(animate);

  var time = Date.now() * 0.002;

  if (particleSystem) {
    if (currentState === 'idle') {
      particleSystem.rotation.y += 0.005;
      particleSystem.rotation.x += 0.002;
    } else if (currentState === 'listening') {
      particleSystem.rotation.y += 0.02;
      var scale = 1.0 + Math.sin(time * 6) * 0.08;
      particleSystem.scale.set(scale, scale, scale);
    } else if (currentState === 'speaking') {
      particleSystem.rotation.y += 0.015;
      var scale = 1.0 + Math.abs(Math.sin(time * 10)) * 0.15;
      particleSystem.scale.set(scale, scale, scale);
    } else if (currentState === 'thinking') {
      particleSystem.rotation.y += 0.04;
      particleSystem.rotation.z += 0.02;
    }
  }

  if (coreMesh) {
    coreMesh.rotation.y -= 0.008;
  }

  renderer.render(scene, camera);
}

window.setReactorState = function(state) {
  currentState = state;
  if (!particleSystem) return;

  var colorAttr = particleSystem.geometry.attributes.color;
  var targetColor = new THREE.Color('#00f3ff');

  if (state === 'listening') {
    targetColor = new THREE.Color('#ff3b30');
  } else if (state === 'speaking') {
    targetColor = new THREE.Color('#30ff6b');
  } else if (state === 'thinking') {
    targetColor = new THREE.Color('#ffcc00');
  }

  for (var i = 0; i < colorAttr.count; i++) {
    colorAttr.setXYZ(i, targetColor.r, targetColor.g, targetColor.b);
  }
  colorAttr.needsUpdate = true;
};

window.addEventListener('DOMContentLoaded', window.init3DLogo);
