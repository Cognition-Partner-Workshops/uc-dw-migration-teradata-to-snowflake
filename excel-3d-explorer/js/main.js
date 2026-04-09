/* ==========================================
   Excel 3D Explorer - Three.js Main Script
   ========================================== */

(function () {
    'use strict';

    // ---- Global State ----
    const state = {
        scene: null,
        camera: null,
        renderer: null,
        clock: null,
        mouse: { x: 0, y: 0 },
        scrollY: 0,
        scrollPercent: 0,
        particles: null,
        gridLines: [],
        floatingCells: [],
        dataCubes: [],
        filterParticles: null,
        sortBars: [],
        uniqueSpheres: [],
        lookupBeam: null,
        stackBlocks: [],
        currentSection: 0,
        animationId: null
    };

    // ---- Color Palette ----
    const colors = {
        cyan: new THREE.Color(0x06b6d4),
        blue: new THREE.Color(0x3b82f6),
        purple: new THREE.Color(0x8b5cf6),
        green: new THREE.Color(0x10b981),
        orange: new THREE.Color(0xf59e0b),
        red: new THREE.Color(0xef4444),
        pink: new THREE.Color(0xec4899),
        white: new THREE.Color(0xe2e8f0),
        dark: new THREE.Color(0x0a0e17)
    };

    // ---- Initialize ----
    function init() {
        setupThreeJS();
        createHeroParticles();
        createFloatingGrid();
        createFloatingCells();
        createFilterVisualization();
        createSortVisualization();
        createUniqueVisualization();
        createLookupVisualization();
        createStackVisualization();
        setupScrollAnimations();
        setupMouseTracking();
        setupNavigation();
        animateCounters();
        animate();
    }

    // ---- Three.js Setup ----
    function setupThreeJS() {
        state.scene = new THREE.Scene();
        state.scene.fog = new THREE.FogExp2(0x0a0e17, 0.015);

        state.camera = new THREE.PerspectiveCamera(
            60,
            window.innerWidth / window.innerHeight,
            0.1,
            1000
        );
        state.camera.position.set(0, 0, 30);

        state.renderer = new THREE.WebGLRenderer({
            canvas: document.getElementById('three-canvas'),
            antialias: true,
            alpha: true
        });
        state.renderer.setSize(window.innerWidth, window.innerHeight);
        state.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        state.renderer.setClearColor(0x0a0e17, 1);

        state.clock = new THREE.Clock();

        // Lights
        var ambientLight = new THREE.AmbientLight(0x334466, 0.5);
        state.scene.add(ambientLight);

        var pointLight1 = new THREE.PointLight(0x06b6d4, 1, 100);
        pointLight1.position.set(10, 10, 20);
        state.scene.add(pointLight1);

        var pointLight2 = new THREE.PointLight(0x8b5cf6, 0.8, 100);
        pointLight2.position.set(-10, -5, 15);
        state.scene.add(pointLight2);

        window.addEventListener('resize', onResize);
    }

    function onResize() {
        state.camera.aspect = window.innerWidth / window.innerHeight;
        state.camera.updateProjectionMatrix();
        state.renderer.setSize(window.innerWidth, window.innerHeight);
    }

    // ---- Hero Particle System ----
    function createHeroParticles() {
        var particleCount = 3000;
        var geometry = new THREE.BufferGeometry();
        var positions = new Float32Array(particleCount * 3);
        var particleColors = new Float32Array(particleCount * 3);
        var sizes = new Float32Array(particleCount);
        var velocities = new Float32Array(particleCount * 3);

        for (var i = 0; i < particleCount; i++) {
            var i3 = i * 3;
            positions[i3] = (Math.random() - 0.5) * 80;
            positions[i3 + 1] = (Math.random() - 0.5) * 60;
            positions[i3 + 2] = (Math.random() - 0.5) * 50 - 10;

            var colorChoice = Math.random();
            var color;
            if (colorChoice < 0.3) color = colors.cyan;
            else if (colorChoice < 0.5) color = colors.blue;
            else if (colorChoice < 0.7) color = colors.purple;
            else if (colorChoice < 0.85) color = colors.green;
            else color = colors.white;

            particleColors[i3] = color.r;
            particleColors[i3 + 1] = color.g;
            particleColors[i3 + 2] = color.b;

            sizes[i] = Math.random() * 2 + 0.5;

            velocities[i3] = (Math.random() - 0.5) * 0.02;
            velocities[i3 + 1] = (Math.random() - 0.5) * 0.02;
            velocities[i3 + 2] = (Math.random() - 0.5) * 0.01;
        }

        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geometry.setAttribute('color', new THREE.BufferAttribute(particleColors, 3));
        geometry.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

        var material = new THREE.PointsMaterial({
            size: 0.15,
            vertexColors: true,
            transparent: true,
            opacity: 0.8,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });

        state.particles = new THREE.Points(geometry, material);
        state.particles.userData.velocities = velocities;
        state.scene.add(state.particles);
    }

    // ---- Floating Grid ----
    function createFloatingGrid() {
        var gridGroup = new THREE.Group();
        var gridMaterial = new THREE.LineBasicMaterial({
            color: 0x1a3a5c,
            transparent: true,
            opacity: 0.15
        });

        // Horizontal lines
        for (var i = -15; i <= 15; i += 1.5) {
            var points = [
                new THREE.Vector3(-25, i, -15),
                new THREE.Vector3(25, i, -15)
            ];
            var lineGeo = new THREE.BufferGeometry().setFromPoints(points);
            var line = new THREE.Line(lineGeo, gridMaterial);
            gridGroup.add(line);
        }

        // Vertical lines
        for (var j = -25; j <= 25; j += 1.5) {
            var points2 = [
                new THREE.Vector3(j, -15, -15),
                new THREE.Vector3(j, 15, -15)
            ];
            var lineGeo2 = new THREE.BufferGeometry().setFromPoints(points2);
            var line2 = new THREE.Line(lineGeo2, gridMaterial);
            gridGroup.add(line2);
        }

        state.gridLines.push(gridGroup);
        state.scene.add(gridGroup);
    }

    // ---- Floating Spreadsheet Cells ----
    function createFloatingCells() {
        var cellData = [
            { text: 'FILTER', color: 0x06b6d4, pos: [-12, 8, -5] },
            { text: 'SORT', color: 0x3b82f6, pos: [14, 6, -8] },
            { text: 'UNIQUE', color: 0x10b981, pos: [-8, -6, -3] },
            { text: 'XLOOKUP', color: 0x8b5cf6, pos: [10, -4, -7] },
            { text: 'LET', color: 0xf59e0b, pos: [-15, 2, -10] },
            { text: 'LAMBDA', color: 0xec4899, pos: [16, 0, -6] },
            { text: 'VSTACK', color: 0xef4444, pos: [-5, 10, -9] },
            { text: 'GROUPBY', color: 0x06b6d4, pos: [6, -8, -4] }
        ];

        cellData.forEach(function (cell) {
            var group = new THREE.Group();

            // Cell background
            var cellGeo = new THREE.BoxGeometry(3, 1.2, 0.1);
            var cellMat = new THREE.MeshPhongMaterial({
                color: cell.color,
                transparent: true,
                opacity: 0.15,
                emissive: cell.color,
                emissiveIntensity: 0.1
            });
            var cellMesh = new THREE.Mesh(cellGeo, cellMat);

            // Cell border
            var edges = new THREE.EdgesGeometry(cellGeo);
            var lineMat = new THREE.LineBasicMaterial({
                color: cell.color,
                transparent: true,
                opacity: 0.4
            });
            var cellEdges = new THREE.LineSegments(edges, lineMat);

            group.add(cellMesh);
            group.add(cellEdges);
            group.position.set(cell.pos[0], cell.pos[1], cell.pos[2]);
            group.userData = {
                originalPos: { x: cell.pos[0], y: cell.pos[1], z: cell.pos[2] },
                speed: Math.random() * 0.3 + 0.2,
                offset: Math.random() * Math.PI * 2
            };

            state.floatingCells.push(group);
            state.scene.add(group);
        });
    }

    // ---- Filter Visualization ----
    function createFilterVisualization() {
        var group = new THREE.Group();
        group.position.set(50, 0, 0);
        group.visible = false;

        // Create funnel shape
        var funnelGeo = new THREE.ConeGeometry(5, 8, 6, 1, true);
        var funnelMat = new THREE.MeshPhongMaterial({
            color: 0x06b6d4,
            transparent: true,
            opacity: 0.15,
            wireframe: true,
            side: THREE.DoubleSide
        });
        var funnel = new THREE.Mesh(funnelGeo, funnelMat);
        funnel.rotation.x = Math.PI;
        group.add(funnel);

        // Data particles going through filter
        var particleCount = 200;
        var particleGeo = new THREE.BufferGeometry();
        var positions = new Float32Array(particleCount * 3);
        var particleColors = new Float32Array(particleCount * 3);

        for (var i = 0; i < particleCount; i++) {
            var i3 = i * 3;
            positions[i3] = (Math.random() - 0.5) * 10;
            positions[i3 + 1] = Math.random() * 12 - 2;
            positions[i3 + 2] = (Math.random() - 0.5) * 10;

            var isFiltered = Math.random() > 0.4;
            if (isFiltered) {
                particleColors[i3] = colors.green.r;
                particleColors[i3 + 1] = colors.green.g;
                particleColors[i3 + 2] = colors.green.b;
            } else {
                particleColors[i3] = colors.red.r;
                particleColors[i3 + 1] = colors.red.g;
                particleColors[i3 + 2] = colors.red.b;
            }
        }

        particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        particleGeo.setAttribute('color', new THREE.BufferAttribute(particleColors, 3));

        var particleMat = new THREE.PointsMaterial({
            size: 0.25,
            vertexColors: true,
            transparent: true,
            opacity: 0.9,
            blending: THREE.AdditiveBlending,
            depthWrite: false
        });

        var filterParticles = new THREE.Points(particleGeo, particleMat);
        group.add(filterParticles);

        state.filterParticles = { group: group, particles: filterParticles, funnel: funnel };
        state.scene.add(group);
    }

    // ---- Sort Visualization ----
    function createSortVisualization() {
        var group = new THREE.Group();
        group.position.set(-50, 0, 0);
        group.visible = false;

        var barCount = 12;
        var values = [];
        for (var i = 0; i < barCount; i++) {
            values.push(Math.random() * 6 + 1);
        }

        values.forEach(function (val, idx) {
            var barGeo = new THREE.BoxGeometry(0.6, val, 0.6);
            var hue = idx / barCount;
            var barColor = new THREE.Color().setHSL(0.5 + hue * 0.3, 0.8, 0.5);
            var barMat = new THREE.MeshPhongMaterial({
                color: barColor,
                transparent: true,
                opacity: 0.8,
                emissive: barColor,
                emissiveIntensity: 0.2
            });
            var bar = new THREE.Mesh(barGeo, barMat);
            bar.position.set(idx * 0.9 - (barCount * 0.9) / 2, val / 2 - 3, 0);
            bar.userData = {
                value: val,
                originalX: idx * 0.9 - (barCount * 0.9) / 2,
                index: idx
            };

            var edgeGeo = new THREE.EdgesGeometry(barGeo);
            var edgeMat = new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.3 });
            var edge = new THREE.LineSegments(edgeGeo, edgeMat);
            bar.add(edge);

            state.sortBars.push(bar);
            group.add(bar);
        });

        state.sortBars.group = group;
        state.scene.add(group);
    }

    // ---- Unique Visualization ----
    function createUniqueVisualization() {
        var group = new THREE.Group();
        group.position.set(50, 0, 0);
        group.visible = false;

        var sphereTypes = [
            { color: 0x06b6d4, count: 4 },
            { color: 0x10b981, count: 3 },
            { color: 0x8b5cf6, count: 5 },
            { color: 0xf59e0b, count: 2 },
            { color: 0xec4899, count: 3 }
        ];

        var allSpheres = [];
        sphereTypes.forEach(function (type) {
            for (var i = 0; i < type.count; i++) {
                var geo = new THREE.SphereGeometry(0.4, 16, 16);
                var mat = new THREE.MeshPhongMaterial({
                    color: type.color,
                    transparent: true,
                    opacity: 0.7,
                    emissive: type.color,
                    emissiveIntensity: 0.3
                });
                var sphere = new THREE.Mesh(geo, mat);
                sphere.position.set(
                    (Math.random() - 0.5) * 8,
                    (Math.random() - 0.5) * 6,
                    (Math.random() - 0.5) * 4
                );
                sphere.userData = {
                    typeColor: type.color,
                    isDuplicate: i > 0,
                    originalPos: sphere.position.clone()
                };
                allSpheres.push(sphere);
                group.add(sphere);
            }
        });

        state.uniqueSpheres = allSpheres;
        state.uniqueSpheres.group = group;
        state.scene.add(group);
    }

    // ---- Lookup Visualization ----
    function createLookupVisualization() {
        var group = new THREE.Group();
        group.position.set(-50, 0, 0);
        group.visible = false;

        // Source table
        var sourceTableGeo = new THREE.BoxGeometry(4, 5, 0.15);
        var sourceTableMat = new THREE.MeshPhongMaterial({
            color: 0x3b82f6,
            transparent: true,
            opacity: 0.2,
            emissive: 0x3b82f6,
            emissiveIntensity: 0.1
        });
        var sourceTable = new THREE.Mesh(sourceTableGeo, sourceTableMat);
        sourceTable.position.set(-4, 0, 0);
        group.add(sourceTable);

        var sourceEdges = new THREE.LineSegments(
            new THREE.EdgesGeometry(sourceTableGeo),
            new THREE.LineBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.5 })
        );
        sourceTable.add(sourceEdges);

        // Target table
        var targetTableGeo = new THREE.BoxGeometry(4, 5, 0.15);
        var targetTableMat = new THREE.MeshPhongMaterial({
            color: 0x10b981,
            transparent: true,
            opacity: 0.2,
            emissive: 0x10b981,
            emissiveIntensity: 0.1
        });
        var targetTable = new THREE.Mesh(targetTableGeo, targetTableMat);
        targetTable.position.set(4, 0, 0);
        group.add(targetTable);

        var targetEdges = new THREE.LineSegments(
            new THREE.EdgesGeometry(targetTableGeo),
            new THREE.LineBasicMaterial({ color: 0x10b981, transparent: true, opacity: 0.5 })
        );
        targetTable.add(targetEdges);

        // Connection beams
        for (var i = 0; i < 5; i++) {
            var y = i * 0.9 - 1.8;
            var points = [
                new THREE.Vector3(-2, y, 0.1),
                new THREE.Vector3(2, y, 0.1)
            ];
            var beamGeo = new THREE.BufferGeometry().setFromPoints(points);
            var beamMat = new THREE.LineBasicMaterial({
                color: 0x06b6d4,
                transparent: true,
                opacity: 0.0
            });
            var beam = new THREE.Line(beamGeo, beamMat);
            beam.userData = { targetOpacity: 0.6, delay: i * 0.2 };
            group.add(beam);

            // Row highlight on source side
            var rowGeo = new THREE.BoxGeometry(3.8, 0.7, 0.02);
            var rowMat = new THREE.MeshBasicMaterial({
                color: 0x06b6d4,
                transparent: true,
                opacity: 0
            });
            var row = new THREE.Mesh(rowGeo, rowMat);
            row.position.set(-4, y, 0.1);
            row.userData = { targetOpacity: 0.15 };
            group.add(row);
        }

        state.lookupBeam = group;
        state.scene.add(group);
    }

    // ---- Stack/Group Visualization ----
    function createStackVisualization() {
        var group = new THREE.Group();
        group.position.set(50, 0, 0);
        group.visible = false;

        var blockColors = [0x06b6d4, 0x3b82f6, 0x8b5cf6, 0x10b981, 0xf59e0b];

        // VSTACK blocks
        for (var i = 0; i < 5; i++) {
            var geo = new THREE.BoxGeometry(3, 0.8, 2);
            var mat = new THREE.MeshPhongMaterial({
                color: blockColors[i],
                transparent: true,
                opacity: 0.6,
                emissive: blockColors[i],
                emissiveIntensity: 0.15
            });
            var block = new THREE.Mesh(geo, mat);

            var edgesGeo = new THREE.EdgesGeometry(geo);
            var edgesMat = new THREE.LineBasicMaterial({
                color: blockColors[i],
                transparent: true,
                opacity: 0.5
            });
            var edgesLine = new THREE.LineSegments(edgesGeo, edgesMat);
            block.add(edgesLine);

            block.position.set((Math.random() - 0.5) * 15, (Math.random() - 0.5) * 10, (Math.random() - 0.5) * 5);
            block.userData = {
                targetY: i * 1 - 2,
                originalPos: block.position.clone()
            };

            state.stackBlocks.push(block);
            group.add(block);
        }

        state.stackBlocks.group = group;
        state.scene.add(group);
    }

    // ---- Scroll Animations ----
    function setupScrollAnimations() {
        gsap.registerPlugin(ScrollTrigger);

        // Reveal animations for all sections
        gsap.utils.toArray('.section-header, .concept-card, .etl-map-card, .summary-card, .etl-insight, .final-cta').forEach(function (el) {
            gsap.from(el, {
                scrollTrigger: {
                    trigger: el,
                    start: 'top 85%',
                    toggleActions: 'play none none reverse'
                },
                opacity: 0,
                y: 40,
                duration: 0.8,
                ease: 'power2.out'
            });
        });

        // Text panels slide in from left
        gsap.utils.toArray('.text-panel').forEach(function (el) {
            gsap.from(el, {
                scrollTrigger: {
                    trigger: el,
                    start: 'top 80%',
                    toggleActions: 'play none none reverse'
                },
                opacity: 0,
                x: -50,
                duration: 0.8,
                ease: 'power2.out'
            });
        });

        // Comparison boxes animate in
        gsap.utils.toArray('.comparison-box').forEach(function (el) {
            gsap.from(el, {
                scrollTrigger: {
                    trigger: el,
                    start: 'top 85%',
                    toggleActions: 'play none none reverse'
                },
                opacity: 0,
                y: 30,
                duration: 0.6,
                ease: 'power2.out',
                delay: 0.3
            });
        });

        // ETL parallel boxes
        gsap.utils.toArray('.etl-parallel').forEach(function (el) {
            gsap.from(el, {
                scrollTrigger: {
                    trigger: el,
                    start: 'top 90%',
                    toggleActions: 'play none none reverse'
                },
                opacity: 0,
                x: 30,
                duration: 0.6,
                ease: 'power2.out',
                delay: 0.5
            });
        });

        // Stagger ETL mapping cards
        var etlCards = gsap.utils.toArray('.etl-map-card');
        if (etlCards.length > 0) {
            gsap.from(etlCards, {
                scrollTrigger: {
                    trigger: '.etl-mapping-grid',
                    start: 'top 80%',
                    toggleActions: 'play none none reverse'
                },
                opacity: 0,
                y: 30,
                stagger: 0.08,
                duration: 0.5,
                ease: 'power2.out'
            });
        }

        // Stagger summary cards
        var summaryCards = gsap.utils.toArray('.summary-card');
        if (summaryCards.length > 0) {
            gsap.from(summaryCards, {
                scrollTrigger: {
                    trigger: '.summary-grid',
                    start: 'top 80%',
                    toggleActions: 'play none none reverse'
                },
                opacity: 0,
                y: 30,
                scale: 0.95,
                stagger: 0.1,
                duration: 0.6,
                ease: 'power2.out'
            });
        }

        // Section-based 3D scene transitions
        setupSectionTriggers();
    }

    function setupSectionTriggers() {
        var sections = document.querySelectorAll('.section');

        // Track which section is active for 3D transitions
        sections.forEach(function (section, index) {
            ScrollTrigger.create({
                trigger: section,
                start: 'top center',
                end: 'bottom center',
                onEnter: function () { transitionToSection(index); },
                onEnterBack: function () { transitionToSection(index); }
            });
        });

        // Scroll progress bar
        ScrollTrigger.create({
            trigger: document.body,
            start: 'top top',
            end: 'bottom bottom',
            onUpdate: function (self) {
                state.scrollPercent = self.progress;
                var progressBar = document.getElementById('scroll-progress');
                if (progressBar) {
                    progressBar.style.width = (self.progress * 100) + '%';
                }

                // Hide scroll indicator after scrolling
                var indicator = document.getElementById('scroll-indicator');
                if (indicator) {
                    if (self.progress > 0.02) {
                        indicator.classList.add('hidden');
                    } else {
                        indicator.classList.remove('hidden');
                    }
                }
            }
        });
    }

    function transitionToSection(index) {
        state.currentSection = index;

        // Update nav active state
        var navLinks = document.querySelectorAll('.nav-link');
        navLinks.forEach(function (link) {
            link.classList.remove('active');
        });
        if (navLinks[index]) {
            navLinks[index].classList.add('active');
        }

        // Hide all viz groups first
        if (state.filterParticles) state.filterParticles.group.visible = false;
        if (state.sortBars.group) state.sortBars.group.visible = false;
        if (state.uniqueSpheres.group) state.uniqueSpheres.group.visible = false;
        if (state.lookupBeam) state.lookupBeam.visible = false;
        if (state.stackBlocks.group) state.stackBlocks.group.visible = false;

        // Show relevant viz and animate camera
        switch (index) {
            case 0: // Hero
                gsap.to(state.camera.position, { x: 0, y: 0, z: 30, duration: 1.5, ease: 'power2.inOut' });
                state.floatingCells.forEach(function (cell) { cell.visible = true; });
                break;
            case 1: // Overview
                gsap.to(state.camera.position, { x: 0, y: 0, z: 25, duration: 1.5, ease: 'power2.inOut' });
                state.floatingCells.forEach(function (cell) { cell.visible = true; });
                break;
            case 2: // Filter
                state.filterParticles.group.visible = true;
                state.filterParticles.group.position.set(12, 0, 5);
                gsap.to(state.camera.position, { x: 5, y: 0, z: 22, duration: 1.5, ease: 'power2.inOut' });
                state.floatingCells.forEach(function (cell) { cell.visible = false; });
                break;
            case 3: // Sort
                state.sortBars.group.visible = true;
                state.sortBars.group.position.set(-12, 0, 5);
                gsap.to(state.camera.position, { x: -5, y: 0, z: 22, duration: 1.5, ease: 'power2.inOut' });
                state.floatingCells.forEach(function (cell) { cell.visible = false; });
                animateSortBars();
                break;
            case 4: // Unique
                state.uniqueSpheres.group.visible = true;
                state.uniqueSpheres.group.position.set(12, 0, 5);
                gsap.to(state.camera.position, { x: 5, y: 0, z: 22, duration: 1.5, ease: 'power2.inOut' });
                state.floatingCells.forEach(function (cell) { cell.visible = false; });
                animateUniqueSpheres();
                break;
            case 5: // XLOOKUP
                state.lookupBeam.visible = true;
                state.lookupBeam.position.set(-12, 0, 5);
                gsap.to(state.camera.position, { x: -5, y: 0, z: 22, duration: 1.5, ease: 'power2.inOut' });
                state.floatingCells.forEach(function (cell) { cell.visible = false; });
                animateLookupBeams();
                break;
            case 6: // LET/LAMBDA
                gsap.to(state.camera.position, { x: 3, y: 0, z: 25, duration: 1.5, ease: 'power2.inOut' });
                state.floatingCells.forEach(function (cell) { cell.visible = false; });
                break;
            case 7: // Stack/Group
                state.stackBlocks.group.visible = true;
                state.stackBlocks.group.position.set(-12, 0, 5);
                gsap.to(state.camera.position, { x: -5, y: 0, z: 22, duration: 1.5, ease: 'power2.inOut' });
                state.floatingCells.forEach(function (cell) { cell.visible = false; });
                animateStackBlocks();
                break;
            case 8: // ETL
                gsap.to(state.camera.position, { x: 0, y: 0, z: 28, duration: 1.5, ease: 'power2.inOut' });
                state.floatingCells.forEach(function (cell) { cell.visible = true; });
                break;
            case 9: // Summary
                gsap.to(state.camera.position, { x: 0, y: 2, z: 30, duration: 1.5, ease: 'power2.inOut' });
                state.floatingCells.forEach(function (cell) { cell.visible = true; });
                break;
        }
    }

    // ---- Section-specific animations ----
    function animateSortBars() {
        var sorted = state.sortBars.slice().sort(function (a, b) { return a.userData.value - b.userData.value; });
        sorted.forEach(function (bar, newIndex) {
            var newX = newIndex * 0.9 - (state.sortBars.length * 0.9) / 2;
            gsap.to(bar.position, {
                x: newX,
                duration: 1,
                delay: newIndex * 0.1,
                ease: 'power2.inOut'
            });
        });
    }

    function animateUniqueSpheres() {
        var typePositions = {};
        var typeIndex = 0;

        state.uniqueSpheres.forEach(function (sphere) {
            var colorKey = sphere.userData.typeColor;
            if (!typePositions[colorKey]) {
                typePositions[colorKey] = {
                    x: typeIndex * 2 - 4,
                    y: 0,
                    z: 0
                };
                typeIndex++;
            }

            if (sphere.userData.isDuplicate) {
                gsap.to(sphere.position, {
                    x: typePositions[colorKey].x,
                    y: typePositions[colorKey].y,
                    z: typePositions[colorKey].z,
                    duration: 1.2,
                    ease: 'power2.inOut'
                });
                gsap.to(sphere.material, {
                    opacity: 0.1,
                    duration: 1.5,
                    ease: 'power2.inOut'
                });
            } else {
                gsap.to(sphere.position, {
                    x: typePositions[colorKey].x,
                    y: typePositions[colorKey].y,
                    z: typePositions[colorKey].z + 0.5,
                    duration: 1,
                    ease: 'power2.inOut'
                });
                gsap.to(sphere.material, {
                    opacity: 1,
                    emissiveIntensity: 0.5,
                    duration: 1,
                    ease: 'power2.inOut'
                });
            }
        });
    }

    function animateLookupBeams() {
        if (!state.lookupBeam) return;
        state.lookupBeam.children.forEach(function (child) {
            if (child.isLine && child.userData.targetOpacity) {
                child.material.opacity = 0;
                gsap.to(child.material, {
                    opacity: child.userData.targetOpacity,
                    duration: 0.5,
                    delay: child.userData.delay || 0,
                    ease: 'power2.out'
                });
            }
            if (child.isMesh && child.userData.targetOpacity !== undefined) {
                child.material.opacity = 0;
                gsap.to(child.material, {
                    opacity: child.userData.targetOpacity,
                    duration: 0.5,
                    delay: 0.3,
                    ease: 'power2.out'
                });
            }
        });
    }

    function animateStackBlocks() {
        state.stackBlocks.forEach(function (block, i) {
            gsap.to(block.position, {
                x: 0,
                y: block.userData.targetY,
                z: 0,
                duration: 1.2,
                delay: i * 0.15,
                ease: 'elastic.out(1, 0.5)'
            });
            gsap.to(block.rotation, {
                x: 0,
                y: 0,
                z: 0,
                duration: 1,
                delay: i * 0.15,
                ease: 'power2.inOut'
            });
        });
    }

    // ---- Mouse Tracking ----
    function setupMouseTracking() {
        document.addEventListener('mousemove', function (e) {
            state.mouse.x = (e.clientX / window.innerWidth) * 2 - 1;
            state.mouse.y = -(e.clientY / window.innerHeight) * 2 + 1;
        });
    }

    // ---- Navigation ----
    function setupNavigation() {
        var navLinks = document.querySelectorAll('.nav-link');
        navLinks.forEach(function (link) {
            link.addEventListener('click', function (e) {
                e.preventDefault();
                var target = this.getAttribute('href');
                var section = document.querySelector(target);
                if (section) {
                    section.scrollIntoView({ behavior: 'smooth' });
                }
            });
        });
    }

    // ---- Counter Animation ----
    function animateCounters() {
        var counters = document.querySelectorAll('.stat-number');
        counters.forEach(function (counter) {
            var target = parseInt(counter.getAttribute('data-count'));
            var observer = new IntersectionObserver(function (entries) {
                entries.forEach(function (entry) {
                    if (entry.isIntersecting) {
                        var start = 0;
                        var duration = 2000;
                        var startTime = null;

                        function updateCounter(timestamp) {
                            if (!startTime) startTime = timestamp;
                            var progress = Math.min((timestamp - startTime) / duration, 1);
                            var eased = 1 - Math.pow(1 - progress, 3);
                            counter.textContent = Math.floor(eased * target);
                            if (progress < 1) {
                                requestAnimationFrame(updateCounter);
                            }
                        }

                        requestAnimationFrame(updateCounter);
                        observer.disconnect();
                    }
                });
            }, { threshold: 0.5 });

            observer.observe(counter);
        });
    }

    // ---- Main Animation Loop ----
    function animate() {
        state.animationId = requestAnimationFrame(animate);

        var time = state.clock.getElapsedTime();
        var delta = state.clock.getDelta();

        // Animate hero particles
        if (state.particles) {
            var positions = state.particles.geometry.attributes.position.array;
            var velocities = state.particles.userData.velocities;

            for (var i = 0; i < positions.length; i += 3) {
                positions[i] += velocities[i] + Math.sin(time * 0.3 + i) * 0.003;
                positions[i + 1] += velocities[i + 1] + Math.cos(time * 0.2 + i) * 0.003;
                positions[i + 2] += velocities[i + 2];

                // Boundary wrapping
                if (positions[i] > 40) positions[i] = -40;
                if (positions[i] < -40) positions[i] = 40;
                if (positions[i + 1] > 30) positions[i + 1] = -30;
                if (positions[i + 1] < -30) positions[i + 1] = 30;
            }

            state.particles.geometry.attributes.position.needsUpdate = true;

            // Slight rotation based on mouse
            state.particles.rotation.y += (state.mouse.x * 0.05 - state.particles.rotation.y) * 0.02;
            state.particles.rotation.x += (state.mouse.y * 0.03 - state.particles.rotation.x) * 0.02;
        }

        // Animate floating cells
        state.floatingCells.forEach(function (cell) {
            if (!cell.visible) return;
            var ud = cell.userData;
            cell.position.y = ud.originalPos.y + Math.sin(time * ud.speed + ud.offset) * 0.8;
            cell.position.x = ud.originalPos.x + Math.cos(time * ud.speed * 0.7 + ud.offset) * 0.5;
            cell.rotation.y = Math.sin(time * 0.3 + ud.offset) * 0.15;
            cell.rotation.x = Math.cos(time * 0.2 + ud.offset) * 0.1;
        });

        // Animate grid lines
        state.gridLines.forEach(function (grid) {
            grid.rotation.x = Math.sin(time * 0.1) * 0.05;
            grid.rotation.y = Math.cos(time * 0.08) * 0.05;
        });

        // Animate filter particles
        if (state.filterParticles && state.filterParticles.group.visible) {
            var filterPos = state.filterParticles.particles.geometry.attributes.position.array;
            for (var j = 0; j < filterPos.length; j += 3) {
                filterPos[j + 1] -= 0.03;

                // Converge toward center as they go down
                var distFromCenter = Math.sqrt(filterPos[j] * filterPos[j] + filterPos[j + 2] * filterPos[j + 2]);
                if (filterPos[j + 1] < 2 && distFromCenter > 1) {
                    filterPos[j] *= 0.99;
                    filterPos[j + 2] *= 0.99;
                }

                // Reset when below
                if (filterPos[j + 1] < -6) {
                    filterPos[j] = (Math.random() - 0.5) * 10;
                    filterPos[j + 1] = 10 + Math.random() * 2;
                    filterPos[j + 2] = (Math.random() - 0.5) * 10;
                }
            }
            state.filterParticles.particles.geometry.attributes.position.needsUpdate = true;

            state.filterParticles.funnel.rotation.y = time * 0.3;
        }

        // Animate sort bars glow
        state.sortBars.forEach(function (bar, i) {
            if (bar.parent && bar.parent.visible) {
                bar.material.emissiveIntensity = 0.2 + Math.sin(time * 2 + i * 0.5) * 0.1;
            }
        });

        // Animate unique spheres pulsing
        state.uniqueSpheres.forEach(function (sphere) {
            if (sphere.parent && sphere.parent.visible && !sphere.userData.isDuplicate) {
                var scale = 1 + Math.sin(time * 2) * 0.1;
                sphere.scale.set(scale, scale, scale);
            }
        });

        // Animate stack blocks rotation
        state.stackBlocks.forEach(function (block) {
            if (block.parent && block.parent.visible) {
                block.material.emissiveIntensity = 0.15 + Math.sin(time * 1.5) * 0.05;
            }
        });

        // Subtle camera sway
        state.camera.position.x += (state.mouse.x * 1.5 - state.camera.position.x + getCameraTargetX()) * 0.02;
        state.camera.position.y += (state.mouse.y * 0.8 - state.camera.position.y + getCameraTargetY()) * 0.02;

        state.renderer.render(state.scene, state.camera);
    }

    function getCameraTargetX() {
        switch (state.currentSection) {
            case 2: case 4: case 6: return 5;
            case 3: case 5: case 7: return -5;
            default: return 0;
        }
    }

    function getCameraTargetY() {
        return state.currentSection === 9 ? 2 : 0;
    }

    // ---- Requirements Document ----
    function writeRequirements() {
        // This is handled externally
    }

    // ---- Start ----
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
