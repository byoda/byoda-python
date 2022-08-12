'use strict';
const MANIFEST = 'flutter-app-manifest';
const TEMP = 'flutter-temp-cache';
const CACHE_NAME = 'flutter-app-cache';
const RESOURCES = {
  "version.json": "b33bb78fa6d4df9fbf05a99140aa137a",
"index.html": "def0c99e8ba93668af581e3143279235",
"/": "def0c99e8ba93668af581e3143279235",
"main.dart.js": "5ad8ed1d905208c98ea1954fef67b875",
"flutter.js": "f85e6fb278b0fd20c349186fb46ae36d",
"favicon.png": "5dcef449791fa27946b3d35ad8803796",
"icons/Icon-192.png": "ac9a721a12bbc803b44f645561ecb1e1",
"icons/Icon-maskable-192.png": "c457ef57daa1d16f64b27b786ec2ea3c",
"icons/Icon-maskable-512.png": "301a7604d45b3e739efc881eb04896ea",
"icons/Icon-512.png": "96e752610906ba2a93c65f8abe1645f1",
"manifest.json": "3cbbd04680bb14dc4d12e16ab9294026",
"assets/images/byoda_logo.svg": "ec63d0bb73674c4536481aae5027ade7",
"assets/images/ic_filter.svg": "60cf494e90ec51b67ce96f7a8316edf3",
"assets/images/ic_avatar_png.png": "6c67baddec09744064668e3f54c13692",
"assets/images/mission.png": "c91ae4bc1546090ea98eeb54be8f5c2f",
"assets/images/ic_climpio.svg": "de1417627beb83e94dcee06dbe5caaa7",
"assets/images/ic_report_svg.svg": "b0ddf92a8d1a14ea7e9b5d7771c65b7e",
"assets/images/ic_recommned_badge_svg.svg": "fd28cdd1978e7ca11f2f518c5fa74dc7",
"assets/images/ic_avatar_svg.svg": "2bfc3e31fd79913ef46ba5af7cf6a707",
"assets/images/ic_followers_svg.svg": "2fdd13419224aa57ecc4e1c2d414bf35",
"assets/images/ic_delete_svg.svg": "5250c6ea90950d82a514d2cf45900a67",
"assets/images/ic_climpio_text_login.svg": "a1d52237b24e16dbbbfcc8ed0d510da7",
"assets/images/landing_app_store.png": "e40f10346d964edeb2bfb1c2767383a9",
"assets/images/ic_product_open_svg.svg": "e85514cc219e2e11e986ea50e957aa51",
"assets/images/ic_clicks_svg.svg": "c3d077ec8afb30840dec130f520319eb",
"assets/images/ic_climpio_login.svg": "da2d396ac8549343ffa345d11da648f6",
"assets/images/ic_views_svg.svg": "c466008cda2031f4c23de7fb1683674e",
"assets/images/landing_social_network.png": "1cef0763a5353f8f8f885fcf4fe51961",
"assets/images/ic_reviews_svg.svg": "ab14e0b3b267b7dbf4156890dab401dc",
"assets/images/hamburger.png": "139e1a31079c3cb59296a81ac57cee2d",
"assets/images/ic_network.svg": "7c10d9bcde88917724edd290c88af4fa",
"assets/images/ic_visibility_svg.svg": "90cc3e0d9a08a85174d939cde0084fc1",
"assets/images/ssn.png": "1fe582d81aece3e819e757bdc6642d3a",
"assets/images/ic_youtube_svg.svg": "194f6450e1bc420f583b69908d63a3d4",
"assets/images/ic_product.svg": "8741785405c36fa02c3e306fc37f5e70",
"assets/images/ic_hambarger.svg": "93505ab7cc50199feb9e5b9ad8cf2f4b",
"assets/images/logo.png": "3a8cd36fd6f841e55e5cae4313b32ea5",
"assets/images/ic_search.png": "0712782bb853056694aa75f2bff0bdac",
"assets/images/ic_avatar_input_svg.svg": "d72dc8bab1eedd4d0ac9202b55aa6a0e",
"assets/images/ic_cross_svg.svg": "84b196d654d8081a25eaea02057954d2",
"assets/images/cross.png": "80a5391698270a272cd00312f731c574",
"assets/images/ic_next_svg.svg": "f8db64ec8050992d5e9a325bcf5c9986",
"assets/images/ic_down_arrow_svg.svg": "64944da21a8942e3044a7df88ebcf38b",
"assets/images/ic_ratings_svg.svg": "10fdebc4d2c59994989c49f28930ea75",
"assets/images/ic_question_svg.svg": "ebb1d1e1c527f03b03b121b5e77687af",
"assets/images/icPlusSvg.svg": "37c97c7ca733b660d44df808285936e6",
"assets/images/landing_google_store.png": "776cbc3722795346b4c20c08c15abd3f",
"assets/images/ic_recommends_svg.svg": "fecd8a53fcab44f0a3ceaa70e8a46264",
"assets/images/ic_vertical_dot.svg": "242b5e29945b114ae575d99c2bd893f1",
"assets/images/ic_recommned_badge_white_svg.svg": "d89b58a2b1f3748ff6e92bb23f5ebd9b",
"assets/images/income.png": "f9d4385f39026c18f434759843217b72",
"assets/images/ic_edit_svg.svg": "c5dca7b4ef3a0e576f231bea99535919",
"assets/images/ic_search.svg": "cd6baa4fa48c8c36c7cd47d2811ae894",
"assets/images/ic_share_svg.svg": "9129b63206043428adbbbf40f5f54227",
"assets/images/ic_review.svg": "f6a99868580b693622df49ea963feb15",
"assets/images/splash_logo.png": "f83961bf023413a5765cb1d968239ec7",
"assets/images/ic_home_svg.svg": "bbdaf0f7c38ea23da1d36dd6a569c67d",
"assets/images/ic_tune.png": "65c3caa070e30c6bbf78e4a6c0d856ef",
"assets/AssetManifest.json": "0dc1619be4cf5723ad33281bd03f2a7e",
"assets/NOTICES": "ad361f47f0c4a2a9744cb0b10d0afd8d",
"assets/FontManifest.json": "7b2a36307916a9721811788013e65289",
"assets/packages/rflutter_alert/assets/images/icon_success.png": "8bb472ce3c765f567aa3f28915c1a8f4",
"assets/packages/rflutter_alert/assets/images/2.0x/icon_success.png": "7d6abdd1b85e78df76b2837996749a43",
"assets/packages/rflutter_alert/assets/images/2.0x/icon_error.png": "2da9704815c606109493d8af19999a65",
"assets/packages/rflutter_alert/assets/images/2.0x/icon_warning.png": "e4606e6910d7c48132912eb818e3a55f",
"assets/packages/rflutter_alert/assets/images/2.0x/icon_info.png": "612ea65413e042e3df408a8548cefe71",
"assets/packages/rflutter_alert/assets/images/2.0x/close.png": "abaa692ee4fa94f76ad099a7a437bd4f",
"assets/packages/rflutter_alert/assets/images/3.0x/icon_success.png": "1c04416085cc343b99d1544a723c7e62",
"assets/packages/rflutter_alert/assets/images/3.0x/icon_error.png": "15ca57e31f94cadd75d8e2b2098239bd",
"assets/packages/rflutter_alert/assets/images/3.0x/icon_warning.png": "e5f369189faa13e7586459afbe4ffab9",
"assets/packages/rflutter_alert/assets/images/3.0x/icon_info.png": "e68e8527c1eb78949351a6582469fe55",
"assets/packages/rflutter_alert/assets/images/3.0x/close.png": "98d2de9ca72dc92b1c9a2835a7464a8c",
"assets/packages/rflutter_alert/assets/images/icon_error.png": "f2b71a724964b51ac26239413e73f787",
"assets/packages/rflutter_alert/assets/images/icon_warning.png": "ccfc1396d29de3ac730da38a8ab20098",
"assets/packages/rflutter_alert/assets/images/icon_info.png": "3f71f68cae4d420cecbf996f37b0763c",
"assets/packages/rflutter_alert/assets/images/close.png": "13c168d8841fcaba94ee91e8adc3617f",
"assets/packages/getwidget/icons/slack.png": "19155b848beeb39c1ffcf743608e2fde",
"assets/packages/getwidget/icons/twitter.png": "caee56343a870ebd76a090642d838139",
"assets/packages/getwidget/icons/linkedin.png": "822742104a63a720313f6a14d3134f61",
"assets/packages/getwidget/icons/dribble.png": "1e36936e4411f32b0e28fd8335495647",
"assets/packages/getwidget/icons/youtube.png": "1bfda73ab724ad40eb8601f1e7dbc1b9",
"assets/packages/getwidget/icons/line.png": "da8d1b531d8189396d68dfcd8cb37a79",
"assets/packages/getwidget/icons/pinterest.png": "d52ccb1e2a8277e4c37b27b234c9f931",
"assets/packages/getwidget/icons/whatsapp.png": "30632e569686a4b84cc68169fb9ce2e1",
"assets/packages/getwidget/icons/google.png": "596c5544c21e9d6cb02b0768f60f589a",
"assets/packages/getwidget/icons/wechat.png": "ba10e8b2421bde565e50dfabc202feb7",
"assets/packages/getwidget/icons/facebook.png": "293dc099a89c74ae34a028b1ecd2c1f0",
"assets/shaders/ink_sparkle.frag": "0c7e35af53a899601ef5dec7db6e15b0",
"assets/fonts/MaterialIcons-Regular.otf": "95db9098c58fd6db106f1116bae85a0b",
"assets/assets/ca/lets-encrypt-r3.pem": "be77e5992c00fcd753d1b9c11d3768f2",
"canvaskit/canvaskit.js": "9d49083c3442cfc15366562eb578b5f3",
"canvaskit/profiling/canvaskit.js": "dfb57a8542220c772374503baaf2632c",
"canvaskit/profiling/canvaskit.wasm": "2c16ab2af3d4fbad52da379264e260e8",
"canvaskit/canvaskit.wasm": "e58017ff67dd1419dbd7b720458fb1af"
};

// The application shell files that are downloaded before a service worker can
// start.
const CORE = [
  "main.dart.js",
"index.html",
"assets/AssetManifest.json",
"assets/FontManifest.json"];
// During install, the TEMP cache is populated with the application shell files.
self.addEventListener("install", (event) => {
  self.skipWaiting();
  return event.waitUntil(
    caches.open(TEMP).then((cache) => {
      return cache.addAll(
        CORE.map((value) => new Request(value, {'cache': 'reload'})));
    })
  );
});

// During activate, the cache is populated with the temp files downloaded in
// install. If this service worker is upgrading from one with a saved
// MANIFEST, then use this to retain unchanged resource files.
self.addEventListener("activate", function(event) {
  return event.waitUntil(async function() {
    try {
      var contentCache = await caches.open(CACHE_NAME);
      var tempCache = await caches.open(TEMP);
      var manifestCache = await caches.open(MANIFEST);
      var manifest = await manifestCache.match('manifest');
      // When there is no prior manifest, clear the entire cache.
      if (!manifest) {
        await caches.delete(CACHE_NAME);
        contentCache = await caches.open(CACHE_NAME);
        for (var request of await tempCache.keys()) {
          var response = await tempCache.match(request);
          await contentCache.put(request, response);
        }
        await caches.delete(TEMP);
        // Save the manifest to make future upgrades efficient.
        await manifestCache.put('manifest', new Response(JSON.stringify(RESOURCES)));
        return;
      }
      var oldManifest = await manifest.json();
      var origin = self.location.origin;
      for (var request of await contentCache.keys()) {
        var key = request.url.substring(origin.length + 1);
        if (key == "") {
          key = "/";
        }
        // If a resource from the old manifest is not in the new cache, or if
        // the MD5 sum has changed, delete it. Otherwise the resource is left
        // in the cache and can be reused by the new service worker.
        if (!RESOURCES[key] || RESOURCES[key] != oldManifest[key]) {
          await contentCache.delete(request);
        }
      }
      // Populate the cache with the app shell TEMP files, potentially overwriting
      // cache files preserved above.
      for (var request of await tempCache.keys()) {
        var response = await tempCache.match(request);
        await contentCache.put(request, response);
      }
      await caches.delete(TEMP);
      // Save the manifest to make future upgrades efficient.
      await manifestCache.put('manifest', new Response(JSON.stringify(RESOURCES)));
      return;
    } catch (err) {
      // On an unhandled exception the state of the cache cannot be guaranteed.
      console.error('Failed to upgrade service worker: ' + err);
      await caches.delete(CACHE_NAME);
      await caches.delete(TEMP);
      await caches.delete(MANIFEST);
    }
  }());
});

// The fetch handler redirects requests for RESOURCE files to the service
// worker cache.
self.addEventListener("fetch", (event) => {
  if (event.request.method !== 'GET') {
    return;
  }
  var origin = self.location.origin;
  var key = event.request.url.substring(origin.length + 1);
  // Redirect URLs to the index.html
  if (key.indexOf('?v=') != -1) {
    key = key.split('?v=')[0];
  }
  if (event.request.url == origin || event.request.url.startsWith(origin + '/#') || key == '') {
    key = '/';
  }
  // If the URL is not the RESOURCE list then return to signal that the
  // browser should take over.
  if (!RESOURCES[key]) {
    return;
  }
  // If the URL is the index.html, perform an online-first request.
  if (key == '/') {
    return onlineFirst(event);
  }
  event.respondWith(caches.open(CACHE_NAME)
    .then((cache) =>  {
      return cache.match(event.request).then((response) => {
        // Either respond with the cached resource, or perform a fetch and
        // lazily populate the cache only if the resource was successfully fetched.
        return response || fetch(event.request).then((response) => {
          if (response && Boolean(response.ok)) {
            cache.put(event.request, response.clone());
          }
          return response;
        });
      })
    })
  );
});

self.addEventListener('message', (event) => {
  // SkipWaiting can be used to immediately activate a waiting service worker.
  // This will also require a page refresh triggered by the main worker.
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
    return;
  }
  if (event.data === 'downloadOffline') {
    downloadOffline();
    return;
  }
});

// Download offline will check the RESOURCES for all files not in the cache
// and populate them.
async function downloadOffline() {
  var resources = [];
  var contentCache = await caches.open(CACHE_NAME);
  var currentContent = {};
  for (var request of await contentCache.keys()) {
    var key = request.url.substring(origin.length + 1);
    if (key == "") {
      key = "/";
    }
    currentContent[key] = true;
  }
  for (var resourceKey of Object.keys(RESOURCES)) {
    if (!currentContent[resourceKey]) {
      resources.push(resourceKey);
    }
  }
  return contentCache.addAll(resources);
}

// Attempt to download the resource online before falling back to
// the offline cache.
function onlineFirst(event) {
  return event.respondWith(
    fetch(event.request).then((response) => {
      return caches.open(CACHE_NAME).then((cache) => {
        cache.put(event.request, response.clone());
        return response;
      });
    }).catch((error) => {
      return caches.open(CACHE_NAME).then((cache) => {
        return cache.match(event.request).then((response) => {
          if (response != null) {
            return response;
          }
          throw error;
        });
      });
    })
  );
}
