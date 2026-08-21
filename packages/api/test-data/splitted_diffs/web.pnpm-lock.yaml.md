### web/pnpm-lock.yaml

```diff

index b7f829a..861e115 100644
--- a/web/pnpm-lock.yaml
+++ b/web/pnpm-lock.yaml
@@ -31,25 +31,25 @@ importers:
   32    32          version: 4.3.1(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
   33    33        '@tanstack/react-devtools':
   34    34          specifier: latest
   35       -        version: 0.10.10(@neodrag/core@3.0.0-next.11)(@types/react-dom@19.2.3(@types/react@19.2.17))(@types/react@19.2.17)(csstype@3.2.3)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(solid-js@1.9.13)
         35 +        version: 0.10.9(@types/react-dom@19.2.3(@types/react@19.2.17))(@types/react@19.2.17)(csstype@3.2.3)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(solid-js@1.9.13)
   36    36        '@tanstack/react-query':
   37    37          specifier: ^5.101.2
   38    38          version: 5.101.2(react@19.2.7)
   39    39        '@tanstack/react-router':
   40    40          specifier: latest
   41       -        version: 1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
         41 +        version: 1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
   42    42        '@tanstack/react-router-devtools':
   43    43          specifier: latest
   44       -        version: 1.167.1(@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(@tanstack/router-core@1.171.22)(csstype@3.2.3)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
         44 +        version: 1.167.0(@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(@tanstack/router-core@1.171.15)(csstype@3.2.3)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
   45    45        '@tanstack/react-router-ssr-query':
   46    46          specifier: latest
   47       -        version: 1.167.1(@tanstack/query-core@5.101.2)(@tanstack/react-query@5.101.2(react@19.2.7))(@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(@tanstack/router-core@1.171.22)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
         47 +        version: 1.167.1(@tanstack/query-core@5.101.2)(@tanstack/react-query@5.101.2(react@19.2.7))(@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(@tanstack/router-core@1.171.15)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
   48    48        '@tanstack/react-start':
   49    49          specifier: latest
   50       -        version: 1.168.44(esbuild@0.28.1)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(rolldown@1.1.3)(supports-color@10.2.2)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
         50 +        version: 1.168.34(esbuild@0.28.1)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
   51    51        '@tanstack/router-plugin':
   52    52          specifier: ^1.132.0
   53       -        version: 1.168.18(@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(supports-color@10.2.2)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
         53 +        version: 1.168.18(@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
   54    54        class-variance-authority:
   55    55          specifier: ^0.7.1
   56    56          version: 0.7.1
@@ -65,12 +65,9 @@ importers:
   66    66        react-dom:
   67    67          specifier: ^19.2.0
   68    68          version: 19.2.7(react@19.2.7)
   69       -      react-syntax-highlighter:
   70       -        specifier: ^16.1.1
   71       -        version: 16.1.1(react@19.2.7)
   72    69        shadcn:
   73    70          specifier: ^4.12.0
   74       -        version: 4.12.0(supports-color@10.2.2)(typescript@6.0.3)
         71 +        version: 4.12.0(typescript@6.0.3)
   75    72        sonner:
   76    73          specifier: ^2.0.7
   77    74          version: 2.0.7(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
@@ -95,7 +92,7 @@ importers:
   96    93          version: 0.8.3(@emnapi/core@1.11.1)(@emnapi/runtime@1.11.1)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
   97    94        '@tanstack/router-cli':
   98    95          specifier: ^1.132.0
   99       -        version: 1.167.17(supports-color@10.2.2)
         96 +        version: 1.167.17
  100    97        '@testing-library/dom':
  101    98          specifier: ^10.4.1
  102    99          version: 10.4.1
@@ -111,15 +108,12 @@ importers:
  112   109        '@types/react-dom':
  113   110          specifier: ^19.2.0
  114   111          version: 19.2.3(@types/react@19.2.17)
  115       -      '@types/react-syntax-highlighter':
  116       -        specifier: ^15.5.13
  117       -        version: 15.5.13
  118   112        '@vitejs/plugin-react':
  119   113          specifier: ^6.0.1
  120   114          version: 6.0.3(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
  121   115        jsdom:
  122   116          specifier: ^28.1.0
  123       -        version: 28.1.0(supports-color@10.2.2)
        117 +        version: 28.1.0
  124   118        typescript:
  125   119          specifier: ^6.0.2
  126   120          version: 6.0.3
@@ -128,7 +122,7 @@ importers:
  129   123          version: 8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0)
  130   124        vitest:
  131   125          specifier: ^4.1.5
  132       -        version: 4.1.9(@types/node@22.20.0)(jsdom@28.1.0(supports-color@10.2.2))(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
        126 +        version: 4.1.9(@types/node@22.20.0)(jsdom@28.1.0)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
  133   127        wrangler:
  134   128          specifier: ^4.70.0
  135   129          version: 4.105.0
@@ -809,15 +803,6 @@ packages:
  810   804        '@emnapi/core': ^1.7.1
  811   805        '@emnapi/runtime': ^1.7.1
  812   806  
  813       -  '@neodrag/core@3.0.0-next.11':
  814       -    resolution: {integrity: sha512-3WQWxyrbxiaK9zS5JU2wJsW2gpoQlZBXVghduBh61JpqaeE0T0cte8R0qYK2RuJo3J2TYQYqxO19CpG/C1i5eg==}
  815       -
  816       -  '@neodrag/solid@3.0.0-next.11':
  817       -    resolution: {integrity: sha512-vCBIn/pimjWMQ6vhTS2/O1XNAwzVtc4eUhdbQ91WykbZWWqQ5NocDXt/1OdYrEkeRzJcpCv8wEz5PnMkgKP81Q==}
  818       -    peerDependencies:
  819       -      '@neodrag/core': 3.0.0-next.11
  820       -      solid-js: ^1.0.0
  821       -
  822   807    '@nodelib/fs.scandir@2.1.5':
  823   808      resolution: {integrity: sha512-vq24Bq3ym5HEQm2NKCr3yXDwjc7vTsEThRDnkp2DK9p1uqLR+DHurm/NOTo0KG7HYHU7eppKZj3MyqYuMBf62g==}
  824   809      engines: {node: '>= 8'}
@@ -1257,8 +1242,8 @@ packages:
 1258  1243      engines: {node: '>=18'}
 1259  1244      hasBin: true
 1260  1245  
 1261       -  '@tanstack/devtools-ui@0.7.0':
 1262       -    resolution: {integrity: sha512-px/a+JgRSVHDj/hID1cwfsIi+ly5l7t3Yw7fLw4G556HXCNgDri36fupt9h7oBeEKntpsx3ep/XtZn51rrCv2g==}
       1246 +  '@tanstack/devtools-ui@0.6.0':
       1247 +    resolution: {integrity: sha512-CVaM6rT6Nl5ijo83vJYFa2SjofvpuOl/uOvbYGhBrRgUhhelNHhx8zZX+hnZCHmIr0/lzM65hsocnZ72592Rvg==}
 1263  1248      engines: {node: '>=18'}
 1264  1249      peerDependencies:
 1265  1250        solid-js: '>=1.9.7'
@@ -1270,8 +1255,8 @@ packages:
 1271  1256      peerDependencies:
 1272  1257        vite: ^6.0.0 || ^7.0.0 || ^8.0.0
 1273  1258  
 1274       -  '@tanstack/devtools@0.14.0':
 1275       -    resolution: {integrity: sha512-tN0SEi1BVaJYtkZbgYpvLsInjwNRAZkR3r6slSvz9Jm+bfkhcdjuOSrZp0cAwOGwdnauHZ1mYgtfe2AfC/V1NQ==}
       1259 +  '@tanstack/devtools@0.13.0':
       1260 +    resolution: {integrity: sha512-p/nOH9bS/OO/u3402zPjoGu+Mz6Fzi/iRqJuYghuuYRUY32kZt+C0/d+pP/bi6/2JTi1FdT6oEXI2lWlA5tXxw==}
 1276  1261      engines: {node: '>=18'}
 1277  1262      hasBin: true
 1278  1263      peerDependencies:
@@ -1281,15 +1266,11 @@ packages:
 1282  1267      resolution: {integrity: sha512-79pf/RkhteYZTRgcR4F9kbk84P2N8rugQJswxfIqovlbRiT3yI7eBE+5QorIrZaOKktsgzRlXh1l/du/xpl4iA==}
 1283  1268      engines: {node: '>=20.19'}
 1284  1269  
 1285       -  '@tanstack/history@1.162.1':
 1286       -    resolution: {integrity: sha512-DR9t6lfLVdrjgCwpglrR9DR7Ok8/HlXjcOE+goWXF3zyuLUO/ug7vMbSFxTqrQTtbRghJfyhmIZ0S6LhPIy44w==}
 1287       -    engines: {node: '>=20.19'}
 1288       -
 1289  1270    '@tanstack/query-core@5.101.2':
 1290  1271      resolution: {integrity: sha512-hH5MLoJhF7KaIGd7q3xTXGXvslI+GYlM1Z/35aSHHWaCJWB7XvTSHYuV3eM7tw+aE0mT/xMro4M4Q9rCGHT0lw==}
 1291  1272  
 1292       -  '@tanstack/react-devtools@0.10.10':
 1293       -    resolution: {integrity: sha512-hYH34MSVbajs1pUc22ftSapyKQp2gOh0w34a7ouYOdIcbXD6YPckSR2YpAWGq1rrs6N0l/rvV6LM/G1pgN5ARg==}
       1273 +  '@tanstack/react-devtools@0.10.9':
       1274 +    resolution: {integrity: sha512-lS6mtccEmUaodsWiRORGM/MGKT0jgzcy5v+eY6pzOPxEgzTHUDhca+WGxShFqKxmF4oneRxXjww1gkvMrWq6uw==}
 1294  1275      engines: {node: '>=18'}
 1295  1276      peerDependencies:
 1296  1277        '@types/react': '>=16.8'
@@ -1302,12 +1283,12 @@ packages:
 1303  1284      peerDependencies:
 1304  1285        react: ^18 || ^19
 1305  1286  
 1306       -  '@tanstack/react-router-devtools@1.167.1':
 1307       -    resolution: {integrity: sha512-pjfGrmjj4d7naEPM7oshqFfwBoxDPNo/UxltlHH5ePbHsJ+plBhd+JaAewm1ueYOjZ0js9hckjWWDYXpCrSfKw==}
       1287 +  '@tanstack/react-router-devtools@1.167.0':
       1288 +    resolution: {integrity: sha512-nGw095EG7IHx0h5NtlEmzf6vcCTaFNPWdTSuDKazajhN0ct/v/TkekJ9J6KYUCeV1a8/2ZmToc58M+0rrOyn7w==}
 1308  1289      engines: {node: '>=20.19'}
 1309  1290      peerDependencies:
 1310       -      '@tanstack/react-router': ^1.170.19
 1311       -      '@tanstack/router-core': ^1.171.16
       1291 +      '@tanstack/react-router': ^1.170.0
       1292 +      '@tanstack/router-core': ^1.170.0
 1312  1293        react: '>=18.0.0 || >=19.0.0'
 1313  1294        react-dom: '>=18.0.0 || >=19.0.0'
 1314  1295      peerDependenciesMeta:
@@ -1324,22 +1305,22 @@ packages:
 1325  1306        react: '>=18.0.0 || >=19.0.0'
 1326  1307        react-dom: '>=18.0.0 || >=19.0.0'
 1327  1308  
 1328       -  '@tanstack/react-router@1.170.27':
 1329       -    resolution: {integrity: sha512-Hxl49xzd8ffWd2ZMigqfXZmpySpixWGvjq5zfh2nK2DbzzDH6IGVh+iUuwarK9MJNcnhWPZ85tOoy6o/OmNlww==}
       1309 +  '@tanstack/react-router@1.170.18':
       1310 +    resolution: {integrity: sha512-wpbGYZEp/fmz1q4bn7BD8VZ+/VZ7GBqSJv5V969pU+chP8y7dquWDmKTFMohvUegb9lg12m1uPVvD6kB2wORvQ==}
 1330  1311      engines: {node: '>=20.19'}
 1331  1312      peerDependencies:
 1332  1313        react: '>=18.0.0 || >=19.0.0'
 1333  1314        react-dom: '>=18.0.0 || >=19.0.0'
 1334  1315  
 1335       -  '@tanstack/react-start-client@1.168.25':
 1336       -    resolution: {integrity: sha512-vwjhuXUXFEAS8btmmXa24J/cP12AuAqIn/9OdZnrVufBE489IaxUEE3KuqEyUyZ+dtwPxChgVxFPHLcG9zonwA==}
       1316 +  '@tanstack/react-start-client@1.168.16':
       1317 +    resolution: {integrity: sha512-1OfHgy0wpHwe2tlB3FxMeA+IMX6Il/QAMf+8UdXuimReIc2Lz3BkMLBL38k4GIxBguX9sI8EMLO5jlTZ4e1olw==}
 1337  1318      engines: {node: '>=22.12.0'}
 1338  1319      peerDependencies:
 1339  1320        react: '>=18.0.0 || >=19.0.0'
 1340  1321        react-dom: '>=18.0.0 || >=19.0.0'
 1341  1322  
 1342       -  '@tanstack/react-start-rsc@0.1.43':
 1343       -    resolution: {integrity: sha512-5h5qytaTlhakTWX0oMz7pVxS/4FuCJeg5a/jKkbLsEU2hWy/R098zQG9tftkWbzPhq+B3pfrGk32ufUzsiwK5A==}
       1323 +  '@tanstack/react-start-rsc@0.1.33':
       1324 +    resolution: {integrity: sha512-G4e1xwi/InoQmIGgNQSozcWASw68/o3NpbTz+exosdMGRZzLBeUDbj0swEAajxHm6jDEOQ/reSeIcDkcEfhMfw==}
 1344  1325      engines: {node: '>=22.12.0'}
 1345  1326      peerDependencies:
 1346  1327        '@rspack/core': '>=2.0.0-0'
@@ -1355,15 +1336,15 @@ packages:
 1356  1337        react-server-dom-rspack:
 1357  1338          optional: true
 1358  1339  
 1359       -  '@tanstack/react-start-server@1.167.32':
 1360       -    resolution: {integrity: sha512-HZV8EE9f2XU+KnyJcB20SCZgAm6G3uGPUwihaqgAz+MPnuJ/xG1iNy1oyQRz/SeqI3PVnPKzWK3Dkv+7xiO7cA==}
       1340 +  '@tanstack/react-start-server@1.167.22':
       1341 +    resolution: {integrity: sha512-eH2PeHuLfL3R5YzE9+y2FfcE4Ld1LNV2ZfrCNVPJMMJFt+9nXDaRHg9BsEmc+JkTAGzz3FKLyQEoWwpbG6Ehqg==}
 1361  1342      engines: {node: '>=22.12.0'}
 1362  1343      peerDependencies:
 1363  1344        react: '>=18.0.0 || >=19.0.0'
 1364  1345        react-dom: '>=18.0.0 || >=19.0.0'
 1365  1346  
 1366       -  '@tanstack/react-start@1.168.44':
 1367       -    resolution: {integrity: sha512-varBaGENYuX0qdRMy8xZvr3BpHCHfkOeBaFCQkXUaOzK3NmWdpqj6CSbPq5uMCHkvFTDXNN6PZukp5zRa5Wmcg==}
       1347 +  '@tanstack/react-start@1.168.34':
       1348 +    resolution: {integrity: sha512-W5MDbD4QlDZHtEXlqN6bJUz7SdsPv6tbNPCih1i72FZqgQlhaxN1BoeoB8H+nN8M4tXRkfJD7VW75FCdQyaQDw==}
 1368  1349      engines: {node: '>=22.12.0'}
 1369  1350      peerDependencies:
 1370  1351        '@rsbuild/core': ^2.0.0
@@ -1394,15 +1375,15 @@ packages:
 1395  1376      resolution: {integrity: sha512-+NOwEj1kO/6IGmpHRIZHasYxYWpyBQGNIZAST9aNrk9Q3YlU9SgqVnl1pbLa9qAKfeNdXQIRve0RQb/0kyDeDA==}
 1396  1377      engines: {node: '>=20.19'}
 1397  1378  
 1398       -  '@tanstack/router-core@1.171.22':
 1399       -    resolution: {integrity: sha512-sitsuRkz4qpTjIAV97S5zFCoeGv0OFd6+VWg3ZcIlQbi5R4NIXfz6ogg51n5w6rvTwSODz/lKWb5dl5tvh2bQw==}
       1379 +  '@tanstack/router-core@1.171.15':
       1380 +    resolution: {integrity: sha512-IILCDcLaItMZQ2jEmCABHY1Nhjjn5XUvwpQp3e4Nmu+vfg0BgYFuu/QASz2SwE2ZNbVMrvt8X/wxa+Gg5aErxA==}
 1400  1381      engines: {node: '>=20.19'}
 1401  1382  
 1402       -  '@tanstack/router-devtools-core@1.168.1':
 1403       -    resolution: {integrity: sha512-qr4voa4cpSMwQvS3867xkU3AB3MtJbTuovKIy+btjJ/Faju6er9w0nDylmD+005Mk/3YKw9/iueZJl2JAB7JOA==}
       1383 +  '@tanstack/router-devtools-core@1.168.0':
       1384 +    resolution: {integrity: sha512-wQoQhlBK7nlZgqzaqdYXKWNTpdHdsaREdaPhFZVH0/Ador+F+eM3/NF2i3f2LPeS0GgKraZUQXe1Q/1+KHyEYg==}
 1404  1385      engines: {node: '>=20.19'}
 1405  1386      peerDependencies:
 1406       -      '@tanstack/router-core': ^1.171.16
       1387 +      '@tanstack/router-core': ^1.170.0
 1407  1388        csstype: ^3.0.10
 1408  1389      peerDependenciesMeta:
 1409  1390        csstype:
@@ -1412,8 +1393,8 @@ packages:
 1413  1394      resolution: {integrity: sha512-xtB9tB2Ws0tWR6Pi7nc3Qk9IYgoh1mQCKWjHqIl9tf6BNUpKoqniJoPAQ4+LGrK8FeZYU0o0p/qlZEyj9FAulA==}
 1414  1395      engines: {node: '>=20.19'}
 1415  1396  
 1416       -  '@tanstack/router-generator@1.167.28':
 1417       -    resolution: {integrity: sha512-AxvzdqQoBxrA8hoO1fHYg4cAUVug/xLqQhsGbNG1PelU3RbYRYEtDim7+HbYQCOqJaEuvV8tCvrTPTnT69iIwg==}
       1397 +  '@tanstack/router-generator@1.167.21':
       1398 +    resolution: {integrity: sha512-m3oXZyienj8owialdyoZ0txHQrnEx/Ra+D9kWtar5fC2cWZr5Pvxl86VY2mX5RRLC5QLKLeRGT1x4HV95wHVDQ==}
 1418  1399      engines: {node: '>=20.19'}
 1419  1400  
 1420  1401    '@tanstack/router-plugin@1.168.18':
@@ -1437,12 +1418,12 @@ packages:
 1438  1419        webpack:
 1439  1420          optional: true
 1440  1421  
 1441       -  '@tanstack/router-plugin@1.168.30':
 1442       -    resolution: {integrity: sha512-Z53FeZjSddyn3c+lmUGHOU3bhZPpaFabcynja8/s87CZeyMYS7oNgUMoaYZAhVLk9cAEC/z3fkqISXqktZadDA==}
       1422 +  '@tanstack/router-plugin@1.168.23':
       1423 +    resolution: {integrity: sha512-0+PIcvnaAimFwjoEIeV3h7LKjzC8zNnp7pH2UamdKwQ9QlY99WU9V0Xl0zbM0i9hrUa/mKgWPDAzELmPUu5fMA==}
 1443  1424      engines: {node: '>=20.19'}
 1444  1425      peerDependencies:
 1445  1426        '@rsbuild/core': '>=1.0.2 || ^2.0.0'
 1446       -      '@tanstack/react-router': ^1.170.26
       1427 +      '@tanstack/react-router': ^1.170.18
 1447  1428        vite: '>=5.0.0 || >=6.0.0 || >=7.0.0 || >=8.0.0'
 1448  1429        vite-plugin-solid: ^2.11.10 || ^3.0.0-0
 1449  1430        webpack: '>=5.92.0'
@@ -1469,16 +1450,16 @@ packages:
 1470  1451      resolution: {integrity: sha512-hTWqJtqIFFdvuCl8WXNyrodp2L9zo2G37xKRrcVmVRWpAB2h+U1LuRAfS4tsFTiWOIoE/B+WDVFB8JpoEdw6jQ==}
 1471  1452      engines: {node: '>=20.19'}
 1472  1453  
 1473       -  '@tanstack/start-client-core@1.170.22':
 1474       -    resolution: {integrity: sha512-18gHvhrVLEmhO0qZVIJaR/y3Mb7tvC9UQnCEiooQG/aIpYg4/kqoQ06E7WUJ/0WFy4NZOkEjk8QkDQNkFED+1g==}
       1454 +  '@tanstack/start-client-core@1.170.14':
       1455 +    resolution: {integrity: sha512-yasBgEIFSWysL4EiFIGwp638nCoXXKiTqkc48EP2oty4OyNsZPTC1yfJ82zjq2KGkTAYtIaeMl7otqqRl1n85Q==}
 1475  1456      engines: {node: '>=22.12.0'}
 1476  1457  
 1477  1458    '@tanstack/start-fn-stubs@1.162.0':
 1478  1459      resolution: {integrity: sha512-QWfUZ3Yo923tdQn38LyKMU8rcTw69zc+T4dAvgTWV4O56SqFRsGfS0lSWIMhJRwXIx/bvdi7nTUBDdZtTHtpTQ==}
 1479  1460      engines: {node: '>=22.12.0'}
 1480  1461  
 1481       -  '@tanstack/start-plugin-core@1.171.34':
 1482       -    resolution: {integrity: sha512-MMp5Mlt8HAtstkVKwHW6dY5w58CP/Vtq+DhXdH4mIPuOeEhFtl/BYErJCzpnq80QqbEpRxCfMZPf9ng2PzApaA==}
       1462 +  '@tanstack/start-plugin-core@1.171.25':
       1463 +    resolution: {integrity: sha512-YmMye36vohfxau/MaVpltjkpJlf+wfUBoZp3S6Ue53mpAnsHr6El3XQDmcp1wS4kicZmyX1SNcobJpVZc+2dOQ==}
 1483  1464      engines: {node: '>=22.12.0'}
 1484  1465      peerDependencies:
 1485  1466        '@rsbuild/core': ^2.0.0
@@ -1489,12 +1470,12 @@ packages:
 1490  1471        vite:
 1491  1472          optional: true
 1492  1473  
 1493       -  '@tanstack/start-server-core@1.169.26':
 1494       -    resolution: {integrity: sha512-57Pvc00i/Y6l8+kqlV/QElVUh5onFUPeMUBDDRNwelAA4eoOmRDmfEWfVfkJNYlcAF4kt/s0mgnD58DlCgC9JA==}
       1474 +  '@tanstack/start-server-core@1.169.17':
       1475 +    resolution: {integrity: sha512-u0N+PHJhMHnzfnlXYI9F+A/qweDe3E2X0mfkORPGIEkNQgvS548RA9fjwvixR2en5b848CfpEqUzwFhm/tQ40Q==}
 1495  1476      engines: {node: '>=22.12.0'}
 1496  1477  
 1497       -  '@tanstack/start-storage-context@1.167.24':
 1498       -    resolution: {integrity: sha512-HPltgydit1LmLJFX3BhMcXMxkmUgtWJopPUx6Eg0YTC4tVwFvUhSWCrfgtTIiGWcHd1Ah+fi6fK9BAe8Y5KZtw==}
       1478 +  '@tanstack/start-storage-context@1.167.17':
       1479 +    resolution: {integrity: sha512-ntkDyGx0PE0opIlWNAMpkMb8qkjR4uyCUOfC0CiT0STM25+EcwPuwYNfDXXeVObMrTAPgsQ4yOj3xdY0Xr4ptw==}
 1499  1480      engines: {node: '>=22.12.0'}
 1500  1481  
 1501  1482    '@tanstack/store@0.9.3':
@@ -1541,32 +1522,17 @@ packages:
 1542  1523    '@types/estree@1.0.9':
 1543  1524      resolution: {integrity: sha512-GhdPgy1el4/ImP05X05Uw4cw2/M93BCUmnEvWZNStlCzEKME4Fkk+YpoA5OiHNQmoS7Cafb8Xa3Pya8m1Qrzeg==}
 1544  1525  
 1545       -  '@types/hast@3.0.5':
 1546       -    resolution: {integrity: sha512-rp/ezSWaD1m44dPKICGhiskI13nVr7qTloFwDa/IYkhhf5nzwP+zIQcIJh3WIFSBOy/H1PzB40jPjMDksN4F+g==}
 1547       -
 1548  1526    '@types/node@22.20.0':
 1549  1527      resolution: {integrity: sha512-QWlFW2wf3nTjC13/DqRnBpR4ZO36VJH/JVBkA/vcnmbTBNQIlnObqyqZE1tUR7+Ni23Lda8R1BxMfbXRpCUx5g==}
 1550  1528  
 1551       -  '@types/prismjs@1.26.6':
 1552       -    resolution: {integrity: sha512-vqlvI7qlMvcCBbVe0AKAb4f97//Hy0EBTaiW8AalRnG/xAN5zOiWWyrNqNXeq8+KAuvRewjCVY1+IPxk4RdNYw==}
 1553       -
 1554  1529    '@types/react-dom@19.2.3':
 1555  1530      resolution: {integrity: sha512-jp2L/eY6fn+KgVVQAOqYItbF0VY/YApe5Mz2F0aykSO8gx31bYCZyvSeYxCHKvzHG5eZjc+zyaS5BrBWya2+kQ==}
 1556  1531      peerDependencies:
 1557  1532        '@types/react': ^19.2.0
 1558  1533  
 1559       -  '@types/react-syntax-highlighter@15.5.13':
 1560       -    resolution: {integrity: sha512-uLGJ87j6Sz8UaBAooU0T6lWJ0dBmjZgN1PZTrj05TNql2/XpC6+4HhMT5syIdFUUt+FASfCeLLv4kBygNU+8qA==}
 1561       -
 1562  1534    '@types/react@19.2.17':
 1563  1535      resolution: {integrity: sha512-MXfmqaVPEVgkBT/aY0aGCkRWWtByiYQXo3xdQ8r5RzuFrPiRn8Gar2tQdXSUQ2GKV3bkXckek89V8wQBY2Q/Aw==}
 1564  1536  
 1565       -  '@types/unist@2.0.11':
 1566       -    resolution: {integrity: sha512-CmBKiL6NNo/OqgmMn95Fk9Whlp2mtvIv+KNpQKN2F4SjvrEesubTRWGYSg+BnWZOnlCaSTU1sMpsBOzgbYhnsA==}
 1567       -
 1568       -  '@types/unist@3.0.3':
 1569       -    resolution: {integrity: sha512-ko/gIFJRv177XgZsZcBwnqJN5x/Gien8qNOn0D5bQU/zAzVf9Zt3BlcUiLqhV9y4ARk0GbT3tnUiPNgnTXzc/Q==}
 1570       -
 1571  1537    '@types/validate-npm-package-name@4.0.2':
 1572  1538      resolution: {integrity: sha512-lrpDziQipxCEeK5kWxvljWYhUvOiB2A9izZd9B2AFarYAkqZshb4lPbRs7zKEic6eGtH8V/2qJW+dPp9OtF6bw==}
 1573  1539  
@@ -1747,15 +1713,6 @@ packages:
 1748  1714      resolution: {integrity: sha512-7NzBL0rN6fMUW+f7A6Io4h40qQlG+xGmtMxfbnH/K7TAtt8JQWVQK+6g0UXKMeVJoyV5EkkNsErQ8pVD3bLHbA==}
 1749  1715      engines: {node: ^12.17.0 || ^14.13 || >=16.0.0}
 1750  1716  
 1751       -  character-entities-legacy@3.0.0:
 1752       -    resolution: {integrity: sha512-RpPp0asT/6ufRm//AJVwpViZbGM/MkjQFxJccQRHmISF/22NBtsHqAWmL+/pmkPWoIUJdWyeVleTl1wydHATVQ==}
 1753       -
 1754       -  character-entities@2.0.2:
 1755       -    resolution: {integrity: sha512-shx7oQ0Awen/BRIdkjkvz54PnEEI/EjwXDSIZp86/KKdbafHh1Df/RYGBhn4hbe2+uKC9FnT5UCEdyPz3ai9hQ==}
 1756       -
 1757       -  character-reference-invalid@2.0.1:
 1758       -    resolution: {integrity: sha512-iBZ4F4wRbyORVsu0jPV7gXkOsGYjGHPmAyv+HiHG8gi5PtC9KI2j1+v8/tlibRvjoWX027ypmG/n0HtO5t7unw==}
 1759       -
 1760  1717    chokidar@5.0.0:
 1761  1718      resolution: {integrity: sha512-TQMmc3w+5AxjpL8iIiwebF73dRDF4fBIieAqGn9RGCWaEVwQ6Fb2cGe31Yns0RRIzii5goJ1Y7xbMwo1TxMplw==}
 1762  1719      engines: {node: '>= 20.19.0'}
@@ -1789,9 +1746,6 @@ packages:
 1790  1747    color-name@1.1.4:
 1791  1748      resolution: {integrity: sha512-dOy+3AuW3a2wNbZHIuMZpTcgjGuLU/uBL/ubcZF9OXbDo8ff4O8yVp5Bf0efS8uEoYo5q4Fx7dY9OgQGXgAsQA==}
 1792  1749  
 1793       -  comma-separated-tokens@2.0.3:
 1794       -    resolution: {integrity: sha512-Fu4hJdvzeylCfQPp9SGWidpzrMs7tTrlu6Vb8XGaRGck8QSNZJJp538Wrb60Lax4fPwR64ViY468OIUTbRlGZg==}
 1795       -
 1796  1750    commander@11.1.0:
 1797  1751      resolution: {integrity: sha512-yPVavfyCcRhmorC7rWlkHn15b4wDVgVmBA7kV4QVBsF7kv/9TKJAbAXVTxvTnwP8HHKjRCJDClKbciiYS7p0DQ==}
 1798  1752      engines: {node: '>=16'}
@@ -1890,9 +1844,6 @@ packages:
 1891  1845    decimal.js@10.6.0:
 1892  1846      resolution: {integrity: sha512-YpgQiITW3JXGntzdUmyUR1V812Hn8T1YVXhCu+wO3OpS4eU9l4YdD3qjyiKdV6mvV29zapkMeD390UVEf2lkUg==}
 1893  1847  
 1894       -  decode-named-character-reference@1.3.0:
 1895       -    resolution: {integrity: sha512-GtpQYB283KrPp6nRw50q3U9/VfOutZOe103qlN7BPP6Ad27xYnOIWv4lPzo8HCAL+mMZofJ9KEy30fq6MfaK6Q==}
 1896       -
 1897  1848    dedent@1.7.2:
 1898  1849      resolution: {integrity: sha512-WzMx3mW98SN+zn3hgemf4OzdmyNhhhKz5Ay0pUfQiMQ3e1g+xmTJWp/pKdwKVXhdSkAEGIIzqeuWrL3mV/AXbA==}
 1899  1850      peerDependencies:
@@ -2075,9 +2026,6 @@ packages:
 2076  2027    fastq@1.20.1:
 2077  2028      resolution: {integrity: sha512-GGToxJ/w1x32s/D2EKND7kTil4n8OVk/9mycTc4VDza13lOvpUZTGX3mFSCtV9ksdGBVzvsyAVLM6mHFThxXxw==}
 2078  2029  
 2079       -  fault@1.0.4:
 2080       -    resolution: {integrity: sha512-CJ0HCB5tL5fYTEA7ToAq5+kTwd++Borf1/bifxd9iT70QcXr4MRrO3Llf8Ifs70q+SJcGHFtnIE/Nw6giCtECA==}
 2081       -
 2082  2030    fdir@6.5.0:
 2083  2031      resolution: {integrity: sha512-tIbYtZbucOs0BRGqPJkshJUYdL+SDH7dVM8gjy+ERp3WAUjLEFJE+02kanyHtwjWOnwrKYBiwAmM0p4kLJAnXg==}
 2084  2032      engines: {node: '>=12.0.0'}
@@ -2106,10 +2054,6 @@ packages:
 2107  2055      resolution: {integrity: sha512-1yD6RmLI1XBfxugvORwlck6f75tYL+iR0jqwsOrOxMZyGYqUuDhJ0l4AXdO1iX/FTs9cBAMEk1gWSEx1kSbylg==}
 2108  2056      engines: {node: '>=6'}
 2109  2057  
 2110       -  format@0.2.2:
 2111       -    resolution: {integrity: sha512-wzsgA6WOq+09wrU1tsJ09udeR/YZRaeArL9e1wPbFg3GG2yDnC2ldKpxs4xunpFF9DgqCqOIra3bc1HWrJ37Ww==}
 2112       -    engines: {node: '>=0.4.x'}
 2113       -
 2114  2058    forwarded@0.2.0:
 2115  2059      resolution: {integrity: sha512-buRG0fpBtRHSTCOASe6hD258tEubFoRLb4ZNA6NxMVHNw2gOcwHo9wyablzMzOA5z9xA9L1KNjk/Nt6MT9aYow==}
 2116  2060      engines: {node: '>= 0.6'}
@@ -2199,18 +2143,6 @@ packages:
 2200  2144      resolution: {integrity: sha512-T2UbfbBEF32wiepXIsMlTW9+dDYC6wMh/t/vYA4tuOMKqWz/n3vr1NFSxQiyP+zk2mXsoMA/i/7qV6LKut1t1A==}
 2201  2145      engines: {node: '>= 0.4'}
 2202  2146  
 2203       -  hast-util-parse-selector@4.0.0:
 2204       -    resolution: {integrity: sha512-wkQCkSYoOGCRKERFWcxMVMOcYE2K1AaNLU8DXS9arxnLOUEWbOXKXiJUNzEpqZ3JOKpnha3jkFrumEjVliDe7A==}
 2205       -
 2206       -  hastscript@9.0.1:
 2207       -    resolution: {integrity: sha512-g7df9rMFX/SPi34tyGCyUBREQoKkapwdY/T04Qn9TDWfHhAYt4/I0gMVirzK5wEzeUqIjEB+LXC/ypb7Aqno5w==}
 2208       -
 2209       -  highlight.js@10.7.3:
 2210       -    resolution: {integrity: sha512-tzcUFauisWKNHaRkN4Wjl/ZA07gENAjFl3J/c480dprkGTg5EQstgaNFqBfUqCq54kZRIEcreTsAgF/m2quD7A==}
 2211       -
 2212       -  highlightjs-vue@1.0.0:
 2213       -    resolution: {integrity: sha512-PDEfEF102G23vHmPhLyPboFCD+BkMGu+GuJe2d9/eH4FsCwvgBpnc9n0pGE+ffKdph38s6foEZiEjdgHdzp+IA==}
 2214       -
 2215  2147    hono@4.12.27:
 2216  2148      resolution: {integrity: sha512-1yrb/+w6HWQJrUCLkJ2IF5jNIPvvFkblV5RNOYl6bV+OA6p9GLcMpHFFGTosSvHvcAUibuUukRqhlYI4z32C7Q==}
 2217  2149      engines: {node: '>=16.9.0'}
@@ -2262,18 +2194,9 @@ packages:
 2263  2195      resolution: {integrity: sha512-0KI/607xoxSToH7GjN1FfSbLoU0+btTicjsQSWQlh/hZykN8KpmMf7uYwPW3R+akZ6R/w18ZlXSHBYXiYUPO3g==}
 2264  2196      engines: {node: '>= 0.10'}
 2265  2197  
 2266       -  is-alphabetical@2.0.1:
 2267       -    resolution: {integrity: sha512-FWyyY60MeTNyeSRpkM2Iry0G9hpr7/9kD40mD/cGQEuilcZYS4okz8SN2Q6rLCJ8gbCt6fN+rC+6tMGS99LaxQ==}
 2268       -
 2269       -  is-alphanumerical@2.0.1:
 2270       -    resolution: {integrity: sha512-hmbYhX/9MUMF5uh7tOXyK/n0ZvWpad5caBA17GsC6vyuCqaWliRG5K1qS9inmUhEMaOBIW7/whAnSwveW/LtZw==}
 2271       -
 2272  2198    is-arrayish@0.2.1:
 2273  2199      resolution: {integrity: sha512-zz06S8t0ozoDXMG+ube26zeCTNXcKIPJZJi8hBrF4idCLms4CG9QtK7qBl1boi5ODzFpjswb5JPmHCbMpjaYzg==}
 2274  2200  
 2275       -  is-decimal@2.0.1:
 2276       -    resolution: {integrity: sha512-AAB9hiomQs5DXWcRB1rqsxGUstbRroFOPPVAomNk/3XHR5JyEZChOyTWe2oayKnsSsr/kcGqF+z6yuH6HHpN0A==}
 2277       -
 2278  2201    is-docker@2.2.1:
 2279  2202      resolution: {integrity: sha512-F+i2BKsFrH66iaUFc0woD8sLy8getkwTwtOBjvs56Cx4CgJDeKQeqfz8wAYiSb8JOprWhHH5p77PbmYCvvUuXQ==}
 2280  2203      engines: {node: '>=8'}
@@ -2296,9 +2219,6 @@ packages:
 2297  2220      resolution: {integrity: sha512-xelSayHH36ZgE7ZWhli7pW34hNbNl8Ojv5KVmkJD4hBdD3th8Tfk9vYasLM+mXWOZhFkgZfxhLSnrwRr4elSSg==}
 2298  2221      engines: {node: '>=0.10.0'}
 2299  2222  
 2300       -  is-hexadecimal@2.0.1:
 2301       -    resolution: {integrity: sha512-DgZQp241c8oO6cA1SbTEWiXeoxV42vlcJxgH+B3hi1AiqqKruZR3ZGF8In3fj4+/y/7rHvlOZLZtgJ/4ttYGZg==}
 2302       -
 2303  2223    is-in-ssh@1.0.0:
 2304  2224      resolution: {integrity: sha512-jYa6Q9rH90kR1vKB6NM7qqd1mge3Fx4Dhw5TVlK1MUBqhEOuCagrEHMevNuCcbECmXZ0ThXkRm+Ymr51HwEPAw==}
 2305  2225      engines: {node: '>=20'}
@@ -2517,9 +2437,6 @@ packages:
 2518  2438      resolution: {integrity: sha512-i24m8rpwhmPIS4zscNzK6MSEhk0DUWa/8iYQWxhffV8jkI4Phvs3F+quL5xvS0gdQR0FyTCMMH33Y78dDTzzIw==}
 2519  2439      engines: {node: '>=18'}
 2520  2440  
 2521       -  lowlight@1.20.0:
 2522       -    resolution: {integrity: sha512-8Ktj+prEb1RoCPkEOrPMYUN/nCggB7qAWe3a7OpMjWQkh3l2RD5wKRQ+o8Q8YuI9RG/xs95waaI/E6ym/7NsTw==}
 2523       -
 2524  2441    lru-cache@11.5.1:
 2525  2442      resolution: {integrity: sha512-RPimw/7aMdv2oqRrxKwvZXcPfwBrn/JZ2xYcY9Hus/6LaS3VOAKVWKWgNLCFSiOm1ESXinjsDlidVU7JlnCN2A==}
 2526  2443      engines: {node: 20 || >=22}
@@ -2685,9 +2602,6 @@ packages:
 2686  2603      resolution: {integrity: sha512-GQ2EWRpQV8/o+Aw8YqtfZZPfNRWZYkbidE9k5rpl/hC3vtHHBfGm2Ifi6qWV+coDGkrUKZAxE3Lot5kcsRlh+g==}
 2687  2604      engines: {node: '>=6'}
 2688  2605  
 2689       -  parse-entities@4.0.2:
 2690       -    resolution: {integrity: sha512-GG2AQYWoLgL877gQIKeRPGO1xF9+eG1ujIb5soS5gPvLQ1y2o8FL90w2QWNdf9I361Mpp7726c+lj3U0qK1uGw==}
 2691       -
 2692  2606    parse-json@5.2.0:
 2693  2607      resolution: {integrity: sha512-ayCKvm/phCGxOkYRSCM82iDwct8/EonSEgCSxWxD7ve6jHggsFl4fZVQBPRNgQoKiuV/odhFrGzQXZwbifC8Rg==}
 2694  2608      engines: {node: '>=8'}
@@ -2775,17 +2689,10 @@ packages:
 2776  2690      resolution: {integrity: sha512-gjVS5hOP+M3wMm5nmNOucbIrqudzs9v/57bWRHQWLYklXqoXKrVfYW2W9+glfGsqtPgpiz5WwyEEB+ksXIx3gQ==}
 2777  2691      engines: {node: '>=18'}
 2778  2692  
 2779       -  prismjs@1.30.0:
 2780       -    resolution: {integrity: sha512-DEvV2ZF2r2/63V+tK8hQvrR2ZGn10srHbXviTlcv7Kpzw8jWiNTqbVgjO3IY8RxrrOUF8VPMQQFysYYYv0YZxw==}
 2781       -    engines: {node: '>=6'}
 2782       -
 2783  2693    prompts@2.4.2:
 2784  2694      resolution: {integrity: sha512-NxNv/kLguCA7p3jE8oL2aEBsrJWgAakBpgmgK6lpPWV+WuOmY6r2/zbAVnP+T8bQlA0nzHXSJSJW0Hq7ylaD2Q==}
 2785  2695      engines: {node: '>= 6'}
 2786  2696  
 2787       -  property-information@7.2.0:
 2788       -    resolution: {integrity: sha512-IAtzIB6sUiWaJYrX9smp3V46pBGbBeLFRGdh25kg1334VcBlD8HzhPeNIWQH9zhGmo2itIe25EHt9dQP7G5hmg==}
 2789       -
 2790  2697    proxy-addr@2.0.7:
 2791  2698      resolution: {integrity: sha512-llQsMLSUDUPT44jdrU/O37qlnifitDP+ZwrmmZcoSKyLKvtZxpyV0n2/bD/N4tBAAZ/gJEdZU7KMraoK1+XYAg==}
 2792  2699      engines: {node: '>= 0.10'}
@@ -2817,12 +2724,6 @@ packages:
 2818  2725    react-is@17.0.2:
 2819  2726      resolution: {integrity: sha512-w2GsyukL62IJnlaff/nRegPQR94C/XXamvMWmSHRJ4y7Ts/4ocGRmTHvOs8PSE6pB3dWOrD/nueuU5sduBsQ4w==}
 2820  2727  
 2821       -  react-syntax-highlighter@16.1.1:
 2822       -    resolution: {integrity: sha512-PjVawBGy80C6YbC5DDZJeUjBmC7skaoEUdvfFQediQHgCL7aKyVHe57SaJGfQsloGDac+gCpTfRdtxzWWKmCXA==}
 2823       -    engines: {node: '>= 16.20.2'}
 2824       -    peerDependencies:
 2825       -      react: '>= 0.14.0'
 2826       -
 2827  2728    react@19.2.7:
 2828  2729      resolution: {integrity: sha512-HNe9WslTbXmFK8o8cmwgAeJFSBvt1bPdHCVKtaaV+WlAN36mpT4hcRpwbf3fY56ar2oIXzsBpOAiIRHAdY0OlQ==}
 2829  2730      engines: {node: '>=0.10.0'}
@@ -2835,9 +2736,6 @@ packages:
 2836  2737      resolution: {integrity: sha512-dEWRjcINDu/F4l2dYx57ugBtD7HV9KXESyxhzw/MqWLeglJrsjJKqACPyUPg+6AF8mIgm+Zi0dZ3ACoIg+QtpA==}
 2837  2738      engines: {node: '>= 4'}
 2838  2739  
 2839       -  refractor@5.0.0:
 2840       -    resolution: {integrity: sha512-QXOrHQF5jOpjjLfiNk5GFnWhRXvxjUVnlFxkeDmewR5sXkr3iM46Zo+CnRR8B+MDVqkULW4EcLVcRBNOPXHosw==}
 2841       -
 2842  2740    require-directory@2.1.1:
 2843  2741      resolution: {integrity: sha512-fGxEI7+wsG9xrvdjsrlmL22OMTTiHRwAMroiEeMgq8gzoLC/PQr7RsRDSTLUg/bZAZtF+TVIkHc6/4RIKrui+Q==}
 2844  2742      engines: {node: '>=0.10.0'}
@@ -2909,20 +2807,10 @@ packages:
 2910  2808      peerDependencies:
 2911  2809        seroval: ^1.0
 2912  2810  
 2913       -  seroval-plugins@1.6.2:
 2914       -    resolution: {integrity: sha512-TfxuUjlbBESzUOWdTkTKqvSmav0ABym+itetDXLK6mDz8SmrpdI30aF8RTXE8Bvq+tH/1yIDkvy3W0lfQb1ipQ==}
 2915       -    engines: {node: '>=10'}
 2916       -    peerDependencies:
 2917       -      seroval: ^1.0
 2918       -
 2919  2811    seroval@1.5.4:
 2920  2812      resolution: {integrity: sha512-46uFvgrXTVxZcUorgSSRZ4y+ieqLLQRMlG4bnCZKW3qI6BZm7Rg4ntMW4p1mILEEBZWrFlcpp0AyIIlM6jD9iw==}
 2921  2813      engines: {node: '>=10'}
 2922  2814  
 2923       -  seroval@1.6.2:
 2924       -    resolution: {integrity: sha512-mPT+SD2TrlB6wvte1KkYOYUkubaTbd6pZ/6Kk3C9nxzrHmCZyhxOO7XGAeL7f+yLKZglzGtM9odUVvg/EhO+vQ==}
 2925       -    engines: {node: '>=10'}
 2926       -
 2927  2815    serve-static@2.2.1:
 2928  2816      resolution: {integrity: sha512-xRXBn0pPqQTVQiC8wyQrKs2MOlX24zQ0POGaj0kultvoOCstBQM5yvOhAVSUwOMjQtTvsPWoNCHfPGwaaQJhTw==}
 2929  2817      engines: {node: '>= 18'}
@@ -3001,9 +2889,6 @@ packages:
 3002  2890      resolution: {integrity: sha512-i5uvt8C3ikiWeNZSVZNWcfZPItFQOsYTUAOkcUPGd8DqDy1uOUikjt5dG+uRlwyvR108Fb9DOd4GvXfT0N2/uQ==}
 3003  2891      engines: {node: '>= 12'}
 3004  2892  
 3005       -  space-separated-tokens@2.0.2:
 3006       -    resolution: {integrity: sha512-PEGlAwrG8yXGXRjW32fGbg66JAlOAwbObuqVoJpv/mRgoWDQfgH1wDPvtzWyUSNAXBGSk8h755YDbbcEy3SH2Q==}
 3007       -
 3008  2893    srvx@0.11.17:
 3009  2894      resolution: {integrity: sha512-43yM4luKfCJamyCMhrUeHUPOrf8TdZe7kN8s5zayZCH5OeprYqi49Aso5ZvHXR4aB+DHaRNO/diNFgZSMNG8Xw==}
 3010  2895      engines: {node: '>=20.16.0'}
@@ -3492,20 +3377,20 @@ snapshots:
 3493  3378  
 3494  3379    '@babel/compat-data@7.29.7': {}
 3495  3380  
 3496       -  '@babel/core@7.29.7(supports-color@10.2.2)':
       3381 +  '@babel/core@7.29.7':
 3497  3382      dependencies:
 3498  3383        '@babel/code-frame': 7.29.7
 3499  3384        '@babel/generator': 7.29.7
 3500  3385        '@babel/helper-compilation-targets': 7.29.7
 3501       -      '@babel/helper-module-transforms': 7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)
       3386 +      '@babel/helper-module-transforms': 7.29.7(@babel/core@7.29.7)
 3502  3387        '@babel/helpers': 7.29.7
 3503  3388        '@babel/parser': 7.29.7
 3504  3389        '@babel/template': 7.29.7
 3505       -      '@babel/traverse': 7.29.7(supports-color@10.2.2)
       3390 +      '@babel/traverse': 7.29.7
 3506  3391        '@babel/types': 7.29.7
 3507  3392        '@jridgewell/remapping': 2.3.5
 3508  3393        convert-source-map: 2.0.0
 3509       -      debug: 4.4.3(supports-color@10.2.2)
       3394 +      debug: 4.4.3
 3510  3395        gensync: 1.0.0-beta.2
 3511  3396        json5: 2.2.3
 3512  3397        semver: 6.3.1
@@ -3532,41 +3417,41 @@ snapshots:
 3533  3418        lru-cache: 5.1.1
 3534  3419        semver: 6.3.1
 3535  3420  
 3536       -  '@babel/helper-create-class-features-plugin@7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)':
       3421 +  '@babel/helper-create-class-features-plugin@7.29.7(@babel/core@7.29.7)':
 3537  3422      dependencies:
 3538       -      '@babel/core': 7.29.7(supports-color@10.2.2)
       3423 +      '@babel/core': 7.29.7
 3539  3424        '@babel/helper-annotate-as-pure': 7.29.7
 3540       -      '@babel/helper-member-expression-to-functions': 7.29.7(supports-color@10.2.2)
       3425 +      '@babel/helper-member-expression-to-functions': 7.29.7
 3541  3426        '@babel/helper-optimise-call-expression': 7.29.7
 3542       -      '@babel/helper-replace-supers': 7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)
 3543       -      '@babel/helper-skip-transparent-expression-wrappers': 7.29.7(supports-color@10.2.2)
 3544       -      '@babel/traverse': 7.29.7(supports-color@10.2.2)
       3427 +      '@babel/helper-replace-supers': 7.29.7(@babel/core@7.29.7)
       3428 +      '@babel/helper-skip-transparent-expression-wrappers': 7.29.7
       3429 +      '@babel/traverse': 7.29.7
 3545  3430        semver: 6.3.1
 3546  3431      transitivePeerDependencies:
 3547  3432        - supports-color
 3548  3433  
 3549  3434    '@babel/helper-globals@7.29.7': {}
 3550  3435  
 3551       -  '@babel/helper-member-expression-to-functions@7.29.7(supports-color@10.2.2)':
       3436 +  '@babel/helper-member-expression-to-functions@7.29.7':
 3552  3437      dependencies:
 3553       -      '@babel/traverse': 7.29.7(supports-color@10.2.2)
       3438 +      '@babel/traverse': 7.29.7
 3554  3439        '@babel/types': 7.29.7
 3555  3440      transitivePeerDependencies:
 3556  3441        - supports-color
 3557  3442  
 3558       -  '@babel/helper-module-imports@7.29.7(supports-color@10.2.2)':
       3443 +  '@babel/helper-module-imports@7.29.7':
 3559  3444      dependencies:
 3560       -      '@babel/traverse': 7.29.7(supports-color@10.2.2)
       3445 +      '@babel/traverse': 7.29.7
 3561  3446        '@babel/types': 7.29.7
 3562  3447      transitivePeerDependencies:
 3563  3448        - supports-color
 3564  3449  
 3565       -  '@babel/helper-module-transforms@7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)':
       3450 +  '@babel/helper-module-transforms@7.29.7(@babel/core@7.29.7)':
 3566  3451      dependencies:
 3567       -      '@babel/core': 7.29.7(supports-color@10.2.2)
 3568       -      '@babel/helper-module-imports': 7.29.7(supports-color@10.2.2)
       3452 +      '@babel/core': 7.29.7
       3453 +      '@babel/helper-module-imports': 7.29.7
 3569  3454        '@babel/helper-validator-identifier': 7.29.7
 3570       -      '@babel/traverse': 7.29.7(supports-color@10.2.2)
       3455 +      '@babel/traverse': 7.29.7
 3571  3456      transitivePeerDependencies:
 3572  3457        - supports-color
 3573  3458  
@@ -3576,18 +3461,18 @@ snapshots:
 3577  3462  
 3578  3463    '@babel/helper-plugin-utils@7.29.7': {}
 3579  3464  
 3580       -  '@babel/helper-replace-supers@7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)':
       3465 +  '@babel/helper-replace-supers@7.29.7(@babel/core@7.29.7)':
 3581  3466      dependencies:
 3582       -      '@babel/core': 7.29.7(supports-color@10.2.2)
 3583       -      '@babel/helper-member-expression-to-functions': 7.29.7(supports-color@10.2.2)
       3467 +      '@babel/core': 7.29.7
       3468 +      '@babel/helper-member-expression-to-functions': 7.29.7
 3584  3469        '@babel/helper-optimise-call-expression': 7.29.7
 3585       -      '@babel/traverse': 7.29.7(supports-color@10.2.2)
       3470 +      '@babel/traverse': 7.29.7
 3586  3471      transitivePeerDependencies:
 3587  3472        - supports-color
 3588  3473  
 3589       -  '@babel/helper-skip-transparent-expression-wrappers@7.29.7(supports-color@10.2.2)':
       3474 +  '@babel/helper-skip-transparent-expression-wrappers@7.29.7':
 3590  3475      dependencies:
 3591       -      '@babel/traverse': 7.29.7(supports-color@10.2.2)
       3476 +      '@babel/traverse': 7.29.7
 3592  3477        '@babel/types': 7.29.7
 3593  3478      transitivePeerDependencies:
 3594  3479        - supports-color
@@ -3607,43 +3492,43 @@ snapshots:
 3608  3493      dependencies:
 3609  3494        '@babel/types': 7.29.7
 3610  3495  
 3611       -  '@babel/plugin-syntax-jsx@7.29.7(@babel/core@7.29.7(supports-color@10.2.2))':
       3496 +  '@babel/plugin-syntax-jsx@7.29.7(@babel/core@7.29.7)':
 3612  3497      dependencies:
 3613       -      '@babel/core': 7.29.7(supports-color@10.2.2)
       3498 +      '@babel/core': 7.29.7
 3614  3499        '@babel/helper-plugin-utils': 7.29.7
 3615  3500  
 3616       -  '@babel/plugin-syntax-typescript@7.29.7(@babel/core@7.29.7(supports-color@10.2.2))':
       3501 +  '@babel/plugin-syntax-typescript@7.29.7(@babel/core@7.29.7)':
 3617  3502      dependencies:
 3618       -      '@babel/core': 7.29.7(supports-color@10.2.2)
       3503 +      '@babel/core': 7.29.7
 3619  3504        '@babel/helper-plugin-utils': 7.29.7
 3620  3505  
 3621       -  '@babel/plugin-transform-modules-commonjs@7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)':
       3506 +  '@babel/plugin-transform-modules-commonjs@7.29.7(@babel/core@7.29.7)':
 3622  3507      dependencies:
 3623       -      '@babel/core': 7.29.7(supports-color@10.2.2)
 3624       -      '@babel/helper-module-transforms': 7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)
       3508 +      '@babel/core': 7.29.7
       3509 +      '@babel/helper-module-transforms': 7.29.7(@babel/core@7.29.7)
 3625  3510        '@babel/helper-plugin-utils': 7.29.7
 3626  3511      transitivePeerDependencies:
 3627  3512        - supports-color
 3628  3513  
 3629       -  '@babel/plugin-transform-typescript@7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)':
       3514 +  '@babel/plugin-transform-typescript@7.29.7(@babel/core@7.29.7)':
 3630  3515      dependencies:
 3631       -      '@babel/core': 7.29.7(supports-color@10.2.2)
       3516 +      '@babel/core': 7.29.7
 3632  3517        '@babel/helper-annotate-as-pure': 7.29.7
 3633       -      '@babel/helper-create-class-features-plugin': 7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)
       3518 +      '@babel/helper-create-class-features-plugin': 7.29.7(@babel/core@7.29.7)
 3634  3519        '@babel/helper-plugin-utils': 7.29.7
 3635       -      '@babel/helper-skip-transparent-expression-wrappers': 7.29.7(supports-color@10.2.2)
 3636       -      '@babel/plugin-syntax-typescript': 7.29.7(@babel/core@7.29.7(supports-color@10.2.2))
       3520 +      '@babel/helper-skip-transparent-expression-wrappers': 7.29.7
       3521 +      '@babel/plugin-syntax-typescript': 7.29.7(@babel/core@7.29.7)
 3637  3522      transitivePeerDependencies:
 3638  3523        - supports-color
 3639  3524  
 3640       -  '@babel/preset-typescript@7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)':
       3525 +  '@babel/preset-typescript@7.29.7(@babel/core@7.29.7)':
 3641  3526      dependencies:
 3642       -      '@babel/core': 7.29.7(supports-color@10.2.2)
       3527 +      '@babel/core': 7.29.7
 3643  3528        '@babel/helper-plugin-utils': 7.29.7
 3644  3529        '@babel/helper-validator-option': 7.29.7
 3645       -      '@babel/plugin-syntax-jsx': 7.29.7(@babel/core@7.29.7(supports-color@10.2.2))
 3646       -      '@babel/plugin-transform-modules-commonjs': 7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)
 3647       -      '@babel/plugin-transform-typescript': 7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)
       3530 +      '@babel/plugin-syntax-jsx': 7.29.7(@babel/core@7.29.7)
       3531 +      '@babel/plugin-transform-modules-commonjs': 7.29.7(@babel/core@7.29.7)
       3532 +      '@babel/plugin-transform-typescript': 7.29.7(@babel/core@7.29.7)
 3648  3533      transitivePeerDependencies:
 3649  3534        - supports-color
 3650  3535  
@@ -3655,7 +3540,7 @@ snapshots:
 3656  3541        '@babel/parser': 7.29.7
 3657  3542        '@babel/types': 7.29.7
 3658  3543  
 3659       -  '@babel/traverse@7.29.7(supports-color@10.2.2)':
       3544 +  '@babel/traverse@7.29.7':
 3660  3545      dependencies:
 3661  3546        '@babel/code-frame': 7.29.7
 3662  3547        '@babel/generator': 7.29.7
@@ -3663,7 +3548,7 @@ snapshots:
 3664  3549        '@babel/parser': 7.29.7
 3665  3550        '@babel/template': 7.29.7
 3666  3551        '@babel/types': 7.29.7
 3667       -      debug: 4.4.3(supports-color@10.2.2)
       3552 +      debug: 4.4.3
 3668  3553      transitivePeerDependencies:
 3669  3554        - supports-color
 3670  3555  
@@ -4027,7 +3912,7 @@ snapshots:
 4028  3913        '@jridgewell/resolve-uri': 3.1.2
 4029  3914        '@jridgewell/sourcemap-codec': 1.5.5
 4030  3915  
 4031       -  '@modelcontextprotocol/sdk@1.29.0(supports-color@10.2.2)(zod@3.25.76)':
       3916 +  '@modelcontextprotocol/sdk@1.29.0(zod@3.25.76)':
 4032  3917      dependencies:
 4033  3918        '@hono/node-server': 1.19.14(hono@4.12.27)
 4034  3919        ajv: 8.20.0
@@ -4037,8 +3922,8 @@ snapshots:
 4038  3923        cross-spawn: 7.0.6
 4039  3924        eventsource: 3.0.7
 4040  3925        eventsource-parser: 3.1.0
 4041       -      express: 5.2.1(supports-color@10.2.2)
 4042       -      express-rate-limit: 8.5.2(express@5.2.1(supports-color@10.2.2))
       3926 +      express: 5.2.1
       3927 +      express-rate-limit: 8.5.2(express@5.2.1)
 4043  3928        hono: 4.12.27
 4044  3929        jose: 6.2.3
 4045  3930        json-schema-typed: 8.0.2
@@ -4056,13 +3941,6 @@ snapshots:
 4057  3942        '@tybys/wasm-util': 0.10.3
 4058  3943      optional: true
 4059  3944  
 4060       -  '@neodrag/core@3.0.0-next.11': {}
 4061       -
 4062       -  '@neodrag/solid@3.0.0-next.11(@neodrag/core@3.0.0-next.11)(solid-js@1.9.13)':
 4063       -    dependencies:
 4064       -      '@neodrag/core': 3.0.0-next.11
 4065       -      solid-js: 1.9.13
 4066       -
 4067  3945    '@nodelib/fs.scandir@2.1.5':
 4068  3946      dependencies:
 4069  3947        '@nodelib/fs.stat': 2.0.5
@@ -4376,7 +4254,7 @@ snapshots:
 4377  4255  
 4378  4256    '@tanstack/devtools-event-client@0.5.0': {}
 4379  4257  
 4380       -  '@tanstack/devtools-ui@0.7.0(csstype@3.2.3)(solid-js@1.9.13)':
       4258 +  '@tanstack/devtools-ui@0.6.0(csstype@3.2.3)(solid-js@1.9.13)':
 4381  4259      dependencies:
 4382  4260        clsx: 2.1.1
 4383  4261        dayjs: 1.11.21
@@ -4398,39 +4276,34 @@ snapshots:
 4399  4277        - bufferutil
 4400  4278        - utf-8-validate
 4401  4279  
 4402       -  '@tanstack/devtools@0.14.0(@neodrag/core@3.0.0-next.11)(csstype@3.2.3)(solid-js@1.9.13)':
       4280 +  '@tanstack/devtools@0.13.0(csstype@3.2.3)(solid-js@1.9.13)':
 4403  4281      dependencies:
 4404       -      '@neodrag/solid': 3.0.0-next.11(@neodrag/core@3.0.0-next.11)(solid-js@1.9.13)
 4405  4282        '@solid-primitives/event-listener': 2.4.5(solid-js@1.9.13)
 4406  4283        '@solid-primitives/keyboard': 1.3.5(solid-js@1.9.13)
 4407  4284        '@solid-primitives/resize-observer': 2.1.5(solid-js@1.9.13)
 4408  4285        '@tanstack/devtools-client': 0.0.8
 4409  4286        '@tanstack/devtools-event-bus': 0.4.2
 4410       -      '@tanstack/devtools-ui': 0.7.0(csstype@3.2.3)(solid-js@1.9.13)
       4287 +      '@tanstack/devtools-ui': 0.6.0(csstype@3.2.3)(solid-js@1.9.13)
 4411  4288        clsx: 2.1.1
 4412  4289        goober: 2.1.19(csstype@3.2.3)
 4413  4290        solid-js: 1.9.13
 4414  4291      transitivePeerDependencies:
 4415       -      - '@neodrag/core'
 4416  4292        - bufferutil
 4417  4293        - csstype
 4418  4294        - utf-8-validate
 4419  4295  
 4420  4296    '@tanstack/history@1.162.0': {}
 4421  4297  
 4422       -  '@tanstack/history@1.162.1': {}
 4423       -
 4424  4298    '@tanstack/query-core@5.101.2': {}
 4425  4299  
 4426       -  '@tanstack/react-devtools@0.10.10(@neodrag/core@3.0.0-next.11)(@types/react-dom@19.2.3(@types/react@19.2.17))(@types/react@19.2.17)(csstype@3.2.3)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(solid-js@1.9.13)':
       4300 +  '@tanstack/react-devtools@0.10.9(@types/react-dom@19.2.3(@types/react@19.2.17))(@types/react@19.2.17)(csstype@3.2.3)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(solid-js@1.9.13)':
 4427  4301      dependencies:
 4428       -      '@tanstack/devtools': 0.14.0(@neodrag/core@3.0.0-next.11)(csstype@3.2.3)(solid-js@1.9.13)
       4302 +      '@tanstack/devtools': 0.13.0(csstype@3.2.3)(solid-js@1.9.13)
 4429  4303        '@types/react': 19.2.17
 4430  4304        '@types/react-dom': 19.2.3(@types/react@19.2.17)
 4431  4305        react: 19.2.7
 4432  4306        react-dom: 19.2.7(react@19.2.7)
 4433  4307      transitivePeerDependencies:
 4434       -      - '@neodrag/core'
 4435  4308        - bufferutil
 4436  4309        - csstype
 4437  4310        - solid-js
@@ -4441,54 +4314,55 @@ snapshots:
 4442  4315        '@tanstack/query-core': 5.101.2
 4443  4316        react: 19.2.7
 4444  4317  
 4445       -  '@tanstack/react-router-devtools@1.167.1(@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(@tanstack/router-core@1.171.22)(csstype@3.2.3)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)':
       4318 +  '@tanstack/react-router-devtools@1.167.0(@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(@tanstack/router-core@1.171.15)(csstype@3.2.3)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)':
 4446  4319      dependencies:
 4447       -      '@tanstack/react-router': 1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
 4448       -      '@tanstack/router-devtools-core': 1.168.1(@tanstack/router-core@1.171.22)(csstype@3.2.3)
       4320 +      '@tanstack/react-router': 1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
       4321 +      '@tanstack/router-devtools-core': 1.168.0(@tanstack/router-core@1.171.15)(csstype@3.2.3)
 4449  4322        react: 19.2.7
 4450  4323        react-dom: 19.2.7(react@19.2.7)
 4451  4324      optionalDependencies:
 4452       -      '@tanstack/router-core': 1.171.22
       4325 +      '@tanstack/router-core': 1.171.15
 4453  4326      transitivePeerDependencies:
 4454  4327        - csstype
 4455  4328  
 4456       -  '@tanstack/react-router-ssr-query@1.167.1(@tanstack/query-core@5.101.2)(@tanstack/react-query@5.101.2(react@19.2.7))(@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(@tanstack/router-core@1.171.22)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)':
       4329 +  '@tanstack/react-router-ssr-query@1.167.1(@tanstack/query-core@5.101.2)(@tanstack/react-query@5.101.2(react@19.2.7))(@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(@tanstack/router-core@1.171.15)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)':
 4457  4330      dependencies:
 4458  4331        '@tanstack/query-core': 5.101.2
 4459  4332        '@tanstack/react-query': 5.101.2(react@19.2.7)
 4460       -      '@tanstack/react-router': 1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
 4461       -      '@tanstack/router-ssr-query-core': 1.169.1(@tanstack/query-core@5.101.2)(@tanstack/router-core@1.171.22)
       4333 +      '@tanstack/react-router': 1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
       4334 +      '@tanstack/router-ssr-query-core': 1.169.1(@tanstack/query-core@5.101.2)(@tanstack/router-core@1.171.15)
 4462  4335        react: 19.2.7
 4463  4336        react-dom: 19.2.7(react@19.2.7)
 4464  4337      transitivePeerDependencies:
 4465  4338        - '@tanstack/router-core'
 4466  4339  
 4467       -  '@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7)':
       4340 +  '@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7)':
 4468  4341      dependencies:
 4469       -      '@tanstack/history': 1.162.1
       4342 +      '@tanstack/history': 1.162.0
 4470  4343        '@tanstack/react-store': 0.9.3(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
 4471       -      '@tanstack/router-core': 1.171.22
       4344 +      '@tanstack/router-core': 1.171.15
 4472  4345        isbot: 5.1.44
 4473  4346        react: 19.2.7
 4474  4347        react-dom: 19.2.7(react@19.2.7)
 4475  4348  
 4476       -  '@tanstack/react-start-client@1.168.25(react-dom@19.2.7(react@19.2.7))(react@19.2.7)':
       4349 +  '@tanstack/react-start-client@1.168.16(react-dom@19.2.7(react@19.2.7))(react@19.2.7)':
 4477  4350      dependencies:
 4478       -      '@tanstack/react-router': 1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
 4479       -      '@tanstack/router-core': 1.171.22
 4480       -      '@tanstack/start-client-core': 1.170.22
       4351 +      '@tanstack/react-router': 1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
       4352 +      '@tanstack/router-core': 1.171.15
       4353 +      '@tanstack/start-client-core': 1.170.14
 4481  4354        react: 19.2.7
 4482  4355        react-dom: 19.2.7(react@19.2.7)
 4483  4356  
 4484       -  '@tanstack/react-start-rsc@0.1.43(esbuild@0.28.1)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(rolldown@1.1.3)(supports-color@10.2.2)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))':
       4357 +  '@tanstack/react-start-rsc@0.1.33(esbuild@0.28.1)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))':
 4485  4358      dependencies:
 4486       -      '@tanstack/react-router': 1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
 4487       -      '@tanstack/router-core': 1.171.22
 4488       -      '@tanstack/router-utils': 1.162.2(supports-color@10.2.2)
 4489       -      '@tanstack/start-client-core': 1.170.22
       4359 +      '@tanstack/react-router': 1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
       4360 +      '@tanstack/router-core': 1.171.15
       4361 +      '@tanstack/router-utils': 1.162.2
       4362 +      '@tanstack/start-client-core': 1.170.14
 4490  4363        '@tanstack/start-fn-stubs': 1.162.0
 4491       -      '@tanstack/start-plugin-core': 1.171.34(@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(supports-color@10.2.2)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
 4492       -      '@tanstack/start-storage-context': 1.167.24
       4364 +      '@tanstack/start-plugin-core': 1.171.25(@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
       4365 +      '@tanstack/start-server-core': 1.169.17
       4366 +      '@tanstack/start-storage-context': 1.167.17
 4493  4367        pathe: 2.0.3
 4494  4368        react: 19.2.7
 4495  4369        react-dom: 19.2.7(react@19.2.7)
@@ -4506,26 +4380,26 @@ snapshots:
 4507  4381        - vite-plugin-solid
 4508  4382        - webpack
 4509  4383  
 4510       -  '@tanstack/react-start-server@1.167.32(react-dom@19.2.7(react@19.2.7))(react@19.2.7)':
       4384 +  '@tanstack/react-start-server@1.167.22(react-dom@19.2.7(react@19.2.7))(react@19.2.7)':
 4511  4385      dependencies:
 4512       -      '@tanstack/react-router': 1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
 4513       -      '@tanstack/router-core': 1.171.22
 4514       -      '@tanstack/start-server-core': 1.169.26
       4386 +      '@tanstack/react-router': 1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
       4387 +      '@tanstack/router-core': 1.171.15
       4388 +      '@tanstack/start-server-core': 1.169.17
 4515  4389        react: 19.2.7
 4516  4390        react-dom: 19.2.7(react@19.2.7)
 4517  4391      transitivePeerDependencies:
 4518  4392        - crossws
 4519  4393  
 4520       -  '@tanstack/react-start@1.168.44(esbuild@0.28.1)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(rolldown@1.1.3)(supports-color@10.2.2)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))':
       4394 +  '@tanstack/react-start@1.168.34(esbuild@0.28.1)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))':
 4521  4395      dependencies:
 4522       -      '@tanstack/react-router': 1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
 4523       -      '@tanstack/react-start-client': 1.168.25(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
 4524       -      '@tanstack/react-start-rsc': 0.1.43(esbuild@0.28.1)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(rolldown@1.1.3)(supports-color@10.2.2)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
 4525       -      '@tanstack/react-start-server': 1.167.32(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
 4526       -      '@tanstack/router-utils': 1.162.2(supports-color@10.2.2)
 4527       -      '@tanstack/start-client-core': 1.170.22
 4528       -      '@tanstack/start-plugin-core': 1.171.34(@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(supports-color@10.2.2)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
 4529       -      '@tanstack/start-server-core': 1.169.26
       4396 +      '@tanstack/react-router': 1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
       4397 +      '@tanstack/react-start-client': 1.168.16(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
       4398 +      '@tanstack/react-start-rsc': 0.1.33(esbuild@0.28.1)(react-dom@19.2.7(react@19.2.7))(react@19.2.7)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
       4399 +      '@tanstack/react-start-server': 1.167.22(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
       4400 +      '@tanstack/router-utils': 1.162.2
       4401 +      '@tanstack/start-client-core': 1.170.14
       4402 +      '@tanstack/start-plugin-core': 1.171.25(@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
       4403 +      '@tanstack/start-server-core': 1.169.17
 4530  4404        pathe: 2.0.3
 4531  4405        react: 19.2.7
 4532  4406        react-dom: 19.2.7(react@19.2.7)
@@ -4552,9 +4426,9 @@ snapshots:
 4553  4427        react-dom: 19.2.7(react@19.2.7)
 4554  4428        use-sync-external-store: 1.6.0(react@19.2.7)
 4555  4429  
 4556       -  '@tanstack/router-cli@1.167.17(supports-color@10.2.2)':
       4430 +  '@tanstack/router-cli@1.167.17':
 4557  4431      dependencies:
 4558       -      '@tanstack/router-generator': 1.167.17(supports-color@10.2.2)
       4432 +      '@tanstack/router-generator': 1.167.17
 4559  4433        chokidar: 5.0.0
 4560  4434        yargs: 17.7.3
 4561  4435      transitivePeerDependencies:
@@ -4567,26 +4441,26 @@ snapshots:
 4568  4442        seroval: 1.5.4
 4569  4443        seroval-plugins: 1.5.4(seroval@1.5.4)
 4570  4444  
 4571       -  '@tanstack/router-core@1.171.22':
       4445 +  '@tanstack/router-core@1.171.15':
 4572  4446      dependencies:
 4573       -      '@tanstack/history': 1.162.1
       4447 +      '@tanstack/history': 1.162.0
 4574  4448        cookie-es: 3.1.1
 4575       -      seroval: 1.6.2
 4576       -      seroval-plugins: 1.6.2(seroval@1.6.2)
       4449 +      seroval: 1.5.4
       4450 +      seroval-plugins: 1.5.4(seroval@1.5.4)
 4577  4451  
 4578       -  '@tanstack/router-devtools-core@1.168.1(@tanstack/router-core@1.171.22)(csstype@3.2.3)':
       4452 +  '@tanstack/router-devtools-core@1.168.0(@tanstack/router-core@1.171.15)(csstype@3.2.3)':
 4579  4453      dependencies:
 4580       -      '@tanstack/router-core': 1.171.22
       4454 +      '@tanstack/router-core': 1.171.15
 4581  4455        clsx: 2.1.1
 4582  4456        goober: 2.1.19(csstype@3.2.3)
 4583  4457      optionalDependencies:
 4584  4458        csstype: 3.2.3
 4585  4459  
 4586       -  '@tanstack/router-generator@1.167.17(supports-color@10.2.2)':
       4460 +  '@tanstack/router-generator@1.167.17':
 4587  4461      dependencies:
 4588  4462        '@babel/types': 7.29.7
 4589  4463        '@tanstack/router-core': 1.171.13
 4590       -      '@tanstack/router-utils': 1.162.2(supports-color@10.2.2)
       4464 +      '@tanstack/router-utils': 1.162.2
 4591  4465        '@tanstack/virtual-file-routes': 1.162.0
 4592  4466        jiti: 2.7.0
 4593  4467        magic-string: 0.30.21
@@ -4595,11 +4469,11 @@ snapshots:
 4596  4470      transitivePeerDependencies:
 4597  4471        - supports-color
 4598  4472  
 4599       -  '@tanstack/router-generator@1.167.28(supports-color@10.2.2)':
       4473 +  '@tanstack/router-generator@1.167.21':
 4600  4474      dependencies:
 4601  4475        '@babel/types': 7.29.7
 4602       -      '@tanstack/router-core': 1.171.22
 4603       -      '@tanstack/router-utils': 1.162.2(supports-color@10.2.2)
       4476 +      '@tanstack/router-core': 1.171.15
       4477 +      '@tanstack/router-utils': 1.162.2
 4604  4478        '@tanstack/virtual-file-routes': 1.162.0
 4605  4479        jiti: 2.7.0
 4606  4480        magic-string: 0.30.21
@@ -4608,19 +4482,19 @@ snapshots:
 4609  4483      transitivePeerDependencies:
 4610  4484        - supports-color
 4611  4485  
 4612       -  '@tanstack/router-plugin@1.168.18(@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(supports-color@10.2.2)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))':
       4486 +  '@tanstack/router-plugin@1.168.18(@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))':
 4613  4487      dependencies:
 4614       -      '@babel/core': 7.29.7(supports-color@10.2.2)
       4488 +      '@babel/core': 7.29.7
 4615  4489        '@babel/template': 7.29.7
 4616  4490        '@babel/types': 7.29.7
 4617  4491        '@tanstack/router-core': 1.171.13
 4618       -      '@tanstack/router-generator': 1.167.17(supports-color@10.2.2)
 4619       -      '@tanstack/router-utils': 1.162.2(supports-color@10.2.2)
       4492 +      '@tanstack/router-generator': 1.167.17
       4493 +      '@tanstack/router-utils': 1.162.2
 4620  4494        chokidar: 5.0.0
 4621  4495        unplugin: 3.2.0(esbuild@0.28.1)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
 4622  4496        zod: 4.4.3
 4623  4497      optionalDependencies:
 4624       -      '@tanstack/react-router': 1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
       4498 +      '@tanstack/react-router': 1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
 4625  4499        vite: 8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0)
 4626  4500      transitivePeerDependencies:
 4627  4501        - '@farmfe/core'
@@ -4632,19 +4506,19 @@ snapshots:
 4633  4507        - supports-color
 4634  4508        - unloader
 4635  4509  
 4636       -  '@tanstack/router-plugin@1.168.30(@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(supports-color@10.2.2)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))':
       4510 +  '@tanstack/router-plugin@1.168.23(@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))':
 4637  4511      dependencies:
 4638       -      '@babel/core': 7.29.7(supports-color@10.2.2)
       4512 +      '@babel/core': 7.29.7
 4639  4513        '@babel/template': 7.29.7
 4640  4514        '@babel/types': 7.29.7
 4641       -      '@tanstack/router-core': 1.171.22
 4642       -      '@tanstack/router-generator': 1.167.28(supports-color@10.2.2)
 4643       -      '@tanstack/router-utils': 1.162.2(supports-color@10.2.2)
       4515 +      '@tanstack/router-core': 1.171.15
       4516 +      '@tanstack/router-generator': 1.167.21
       4517 +      '@tanstack/router-utils': 1.162.2
 4644  4518        chokidar: 5.0.0
 4645  4519        unplugin: 3.2.0(esbuild@0.28.1)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
 4646  4520        zod: 4.4.3
 4647  4521      optionalDependencies:
 4648       -      '@tanstack/react-router': 1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
       4522 +      '@tanstack/react-router': 1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7)
 4649  4523        vite: 8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0)
 4650  4524      transitivePeerDependencies:
 4651  4525        - '@farmfe/core'
@@ -4656,48 +4530,48 @@ snapshots:
 4657  4531        - supports-color
 4658  4532        - unloader
 4659  4533  
 4660       -  '@tanstack/router-ssr-query-core@1.169.1(@tanstack/query-core@5.101.2)(@tanstack/router-core@1.171.22)':
       4534 +  '@tanstack/router-ssr-query-core@1.169.1(@tanstack/query-core@5.101.2)(@tanstack/router-core@1.171.15)':
 4661  4535      dependencies:
 4662  4536        '@tanstack/query-core': 5.101.2
 4663       -      '@tanstack/router-core': 1.171.22
       4537 +      '@tanstack/router-core': 1.171.15
 4664  4538  
 4665       -  '@tanstack/router-utils@1.162.2(supports-color@10.2.2)':
       4539 +  '@tanstack/router-utils@1.162.2':
 4666  4540      dependencies:
 4667  4541        '@babel/generator': 7.29.7
 4668  4542        '@babel/parser': 7.29.7
 4669  4543        '@babel/types': 7.29.7
 4670  4544        ansis: 4.3.1
 4671       -      babel-dead-code-elimination: 1.0.12(supports-color@10.2.2)
       4545 +      babel-dead-code-elimination: 1.0.12
 4672  4546        diff: 8.0.4
 4673  4547        pathe: 2.0.3
 4674  4548        tinyglobby: 0.2.17
 4675  4549      transitivePeerDependencies:
 4676  4550        - supports-color
 4677  4551  
 4678       -  '@tanstack/start-client-core@1.170.22':
       4552 +  '@tanstack/start-client-core@1.170.14':
 4679  4553      dependencies:
 4680       -      '@tanstack/router-core': 1.171.22
       4554 +      '@tanstack/router-core': 1.171.15
 4681  4555        '@tanstack/start-fn-stubs': 1.162.0
 4682       -      '@tanstack/start-storage-context': 1.167.24
 4683       -      seroval: 1.6.2
       4556 +      '@tanstack/start-storage-context': 1.167.17
       4557 +      seroval: 1.5.4
 4684  4558  
 4685  4559    '@tanstack/start-fn-stubs@1.162.0': {}
 4686  4560  
 4687       -  '@tanstack/start-plugin-core@1.171.34(@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(supports-color@10.2.2)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))':
       4561 +  '@tanstack/start-plugin-core@1.171.25(@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))':
 4688  4562      dependencies:
 4689  4563        '@babel/code-frame': 7.27.1
 4690       -      '@babel/core': 7.29.7(supports-color@10.2.2)
       4564 +      '@babel/core': 7.29.7
 4691  4565        '@babel/types': 7.29.7
 4692       -      '@tanstack/router-core': 1.171.22
 4693       -      '@tanstack/router-generator': 1.167.28(supports-color@10.2.2)
 4694       -      '@tanstack/router-plugin': 1.168.30(@tanstack/react-router@1.170.27(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(supports-color@10.2.2)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
 4695       -      '@tanstack/router-utils': 1.162.2(supports-color@10.2.2)
 4696       -      '@tanstack/start-server-core': 1.169.26
       4566 +      '@tanstack/router-core': 1.171.15
       4567 +      '@tanstack/router-generator': 1.167.21
       4568 +      '@tanstack/router-plugin': 1.168.23(@tanstack/react-router@1.170.18(react-dom@19.2.7(react@19.2.7))(react@19.2.7))(esbuild@0.28.1)(rolldown@1.1.3)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
       4569 +      '@tanstack/router-utils': 1.162.2
       4570 +      '@tanstack/start-server-core': 1.169.17
 4697  4571        exsolve: 1.1.0
 4698  4572        lightningcss: 1.32.0
 4699  4573        pathe: 2.0.3
 4700  4574        picomatch: 4.0.4
 4701       -      seroval: 1.6.2
       4575 +      seroval: 1.5.4
 4702  4576        source-map: 0.7.6
 4703  4577        srvx: 0.11.17
 4704  4578        tinyglobby: 0.2.17
@@ -4721,21 +4595,21 @@ snapshots:
 4722  4596        - vite-plugin-solid
 4723  4597        - webpack
 4724  4598  
 4725       -  '@tanstack/start-server-core@1.169.26':
       4599 +  '@tanstack/start-server-core@1.169.17':
 4726  4600      dependencies:
 4727       -      '@tanstack/history': 1.162.1
 4728       -      '@tanstack/router-core': 1.171.22
 4729       -      '@tanstack/start-client-core': 1.170.22
 4730       -      '@tanstack/start-storage-context': 1.167.24
       4601 +      '@tanstack/history': 1.162.0
       4602 +      '@tanstack/router-core': 1.171.15
       4603 +      '@tanstack/start-client-core': 1.170.14
       4604 +      '@tanstack/start-storage-context': 1.167.17
 4731  4605        fetchdts: 0.1.7
 4732  4606        h3-v2: h3@2.0.1-rc.20
 4733       -      seroval: 1.6.2
       4607 +      seroval: 1.5.4
 4734  4608      transitivePeerDependencies:
 4735  4609        - crossws
 4736  4610  
 4737       -  '@tanstack/start-storage-context@1.167.24':
       4611 +  '@tanstack/start-storage-context@1.167.17':
 4738  4612      dependencies:
 4739       -      '@tanstack/router-core': 1.171.22
       4613 +      '@tanstack/router-core': 1.171.15
 4740  4614  
 4741  4615    '@tanstack/store@0.9.3': {}
 4742  4616  
@@ -4784,32 +4658,18 @@ snapshots:
 4785  4659  
 4786  4660    '@types/estree@1.0.9': {}
 4787  4661  
 4788       -  '@types/hast@3.0.5':
 4789       -    dependencies:
 4790       -      '@types/unist': 3.0.3
 4791       -
 4792  4662    '@types/node@22.20.0':
 4793  4663      dependencies:
 4794  4664        undici-types: 6.21.0
 4795  4665  
 4796       -  '@types/prismjs@1.26.6': {}
 4797       -
 4798  4666    '@types/react-dom@19.2.3(@types/react@19.2.17)':
 4799  4667      dependencies:
 4800  4668        '@types/react': 19.2.17
 4801  4669  
 4802       -  '@types/react-syntax-highlighter@15.5.13':
 4803       -    dependencies:
 4804       -      '@types/react': 19.2.17
 4805       -
 4806  4670    '@types/react@19.2.17':
 4807  4671      dependencies:
 4808  4672        csstype: 3.2.3
 4809  4673  
 4810       -  '@types/unist@2.0.11': {}
 4811       -
 4812       -  '@types/unist@3.0.3': {}
 4813       -
 4814  4674    '@types/validate-npm-package-name@4.0.2': {}
 4815  4675  
 4816  4676    '@vitejs/plugin-react@6.0.3(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))':
@@ -4908,11 +4768,11 @@ snapshots:
 4909  4769  
 4910  4770    atomically@1.7.0: {}
 4911  4771  
 4912       -  babel-dead-code-elimination@1.0.12(supports-color@10.2.2):
       4772 +  babel-dead-code-elimination@1.0.12:
 4913  4773      dependencies:
 4914       -      '@babel/core': 7.29.7(supports-color@10.2.2)
       4774 +      '@babel/core': 7.29.7
 4915  4775        '@babel/parser': 7.29.7
 4916       -      '@babel/traverse': 7.29.7(supports-color@10.2.2)
       4776 +      '@babel/traverse': 7.29.7
 4917  4777        '@babel/types': 7.29.7
 4918  4778      transitivePeerDependencies:
 4919  4779        - supports-color
@@ -4927,11 +4787,11 @@ snapshots:
 4928  4788  
 4929  4789    blake3-wasm@2.1.5: {}
 4930  4790  
 4931       -  body-parser@2.3.0(supports-color@10.2.2):
       4791 +  body-parser@2.3.0:
 4932  4792      dependencies:
 4933  4793        bytes: 3.1.2
 4934  4794        content-type: 2.0.0
 4935       -      debug: 4.4.3(supports-color@10.2.2)
       4795 +      debug: 4.4.3
 4936  4796        http-errors: 2.0.1
 4937  4797        iconv-lite: 0.7.2
 4938  4798        on-finished: 2.4.1
@@ -4981,12 +4841,6 @@ snapshots:
 4982  4842  
 4983  4843    chalk@5.6.2: {}
 4984  4844  
 4985       -  character-entities-legacy@3.0.0: {}
 4986       -
 4987       -  character-entities@2.0.2: {}
 4988       -
 4989       -  character-reference-invalid@2.0.1: {}
 4990       -
 4991  4845    chokidar@5.0.0:
 4992  4846      dependencies:
 4993  4847        readdirp: 5.0.0
@@ -5017,8 +4871,6 @@ snapshots:
 5018  4872  
 5019  4873    color-name@1.1.4: {}
 5020  4874  
 5021       -  comma-separated-tokens@2.0.3: {}
 5022       -
 5023  4875    commander@11.1.0: {}
 5024  4876  
 5025  4877    commander@14.0.3: {}
@@ -5101,18 +4953,12 @@ snapshots:
 5102  4954      dependencies:
 5103  4955        mimic-fn: 3.1.0
 5104  4956  
 5105       -  debug@4.4.3(supports-color@10.2.2):
       4957 +  debug@4.4.3:
 5106  4958      dependencies:
 5107  4959        ms: 2.1.3
 5108       -    optionalDependencies:
 5109       -      supports-color: 10.2.2
 5110  4960  
 5111  4961    decimal.js@10.6.0: {}
 5112  4962  
 5113       -  decode-named-character-reference@1.3.0:
 5114       -    dependencies:
 5115       -      character-entities: 2.0.2
 5116       -
 5117  4963    dedent@1.7.2: {}
 5118  4964  
 5119  4965    deepmerge@4.3.1: {}
@@ -5266,25 +5112,25 @@ snapshots:
 5267  5113  
 5268  5114    expect-type@1.4.0: {}
 5269  5115  
 5270       -  express-rate-limit@8.5.2(express@5.2.1(supports-color@10.2.2)):
       5116 +  express-rate-limit@8.5.2(express@5.2.1):
 5271  5117      dependencies:
 5272       -      express: 5.2.1(supports-color@10.2.2)
       5118 +      express: 5.2.1
 5273  5119        ip-address: 10.2.0
 5274  5120  
 5275       -  express@5.2.1(supports-color@10.2.2):
       5121 +  express@5.2.1:
 5276  5122      dependencies:
 5277  5123        accepts: 2.0.0
 5278       -      body-parser: 2.3.0(supports-color@10.2.2)
       5124 +      body-parser: 2.3.0
 5279  5125        content-disposition: 1.1.0
 5280  5126        content-type: 1.0.5
 5281  5127        cookie: 0.7.2
 5282  5128        cookie-signature: 1.2.2
 5283       -      debug: 4.4.3(supports-color@10.2.2)
       5129 +      debug: 4.4.3
 5284  5130        depd: 2.0.0
 5285  5131        encodeurl: 2.0.0
 5286  5132        escape-html: 1.0.3
 5287  5133        etag: 1.8.1
 5288       -      finalhandler: 2.1.1(supports-color@10.2.2)
       5134 +      finalhandler: 2.1.1
 5289  5135        fresh: 2.0.0
 5290  5136        http-errors: 2.0.1
 5291  5137        merge-descriptors: 2.0.0
@@ -5295,9 +5141,9 @@ snapshots:
 5296  5142        proxy-addr: 2.0.7
 5297  5143        qs: 6.15.3
 5298  5144        range-parser: 1.3.0
 5299       -      router: 2.2.0(supports-color@10.2.2)
 5300       -      send: 1.2.1(supports-color@10.2.2)
 5301       -      serve-static: 2.2.1(supports-color@10.2.2)
       5145 +      router: 2.2.0
       5146 +      send: 1.2.1
       5147 +      serve-static: 2.2.1
 5302  5148        statuses: 2.0.2
 5303  5149        type-is: 2.1.0
 5304  5150        vary: 1.1.2
@@ -5322,10 +5168,6 @@ snapshots:
 5323  5169      dependencies:
 5324  5170        reusify: 1.1.0
 5325  5171  
 5326       -  fault@1.0.4:
 5327       -    dependencies:
 5328       -      format: 0.2.2
 5329       -
 5330  5172    fdir@6.5.0(picomatch@4.0.4):
 5331  5173      optionalDependencies:
 5332  5174        picomatch: 4.0.4
@@ -5340,9 +5182,9 @@ snapshots:
 5341  5183      dependencies:
 5342  5184        to-regex-range: 5.0.1
 5343  5185  
 5344       -  finalhandler@2.1.1(supports-color@10.2.2):
       5186 +  finalhandler@2.1.1:
 5345  5187      dependencies:
 5346       -      debug: 4.4.3(supports-color@10.2.2)
       5188 +      debug: 4.4.3
 5347  5189        encodeurl: 2.0.0
 5348  5190        escape-html: 1.0.3
 5349  5191        on-finished: 2.4.1
@@ -5355,8 +5197,6 @@ snapshots:
 5356  5198      dependencies:
 5357  5199        locate-path: 3.0.0
 5358  5200  
 5359       -  format@0.2.2: {}
 5360       -
 5361  5201    forwarded@0.2.0: {}
 5362  5202  
 5363  5203    fresh@2.0.0: {}
@@ -5430,22 +5270,6 @@ snapshots:
 5431  5271      dependencies:
 5432  5272        function-bind: 1.1.2
 5433  5273  
 5434       -  hast-util-parse-selector@4.0.0:
 5435       -    dependencies:
 5436       -      '@types/hast': 3.0.5
 5437       -
 5438       -  hastscript@9.0.1:
 5439       -    dependencies:
 5440       -      '@types/hast': 3.0.5
 5441       -      comma-separated-tokens: 2.0.3
 5442       -      hast-util-parse-selector: 4.0.0
 5443       -      property-information: 7.2.0
 5444       -      space-separated-tokens: 2.0.2
 5445       -
 5446       -  highlight.js@10.7.3: {}
 5447       -
 5448       -  highlightjs-vue@1.0.0: {}
 5449       -
 5450  5274    hono@4.12.27: {}
 5451  5275  
 5452  5276    html-encoding-sniffer@6.0.0:
@@ -5462,17 +5286,17 @@ snapshots:
 5463  5287        statuses: 2.0.2
 5464  5288        toidentifier: 1.0.1
 5465  5289  
 5466       -  http-proxy-agent@7.0.2(supports-color@10.2.2):
       5290 +  http-proxy-agent@7.0.2:
 5467  5291      dependencies:
 5468  5292        agent-base: 7.1.4
 5469       -      debug: 4.4.3(supports-color@10.2.2)
       5293 +      debug: 4.4.3
 5470  5294      transitivePeerDependencies:
 5471  5295        - supports-color
 5472  5296  
 5473       -  https-proxy-agent@7.0.6(supports-color@10.2.2):
       5297 +  https-proxy-agent@7.0.6:
 5474  5298      dependencies:
 5475  5299        agent-base: 7.1.4
 5476       -      debug: 4.4.3(supports-color@10.2.2)
       5300 +      debug: 4.4.3
 5477  5301      transitivePeerDependencies:
 5478  5302        - supports-color
 5479  5303  
@@ -5497,17 +5321,8 @@ snapshots:
 5498  5322  
 5499  5323    ipaddr.js@1.9.1: {}
 5500  5324  
 5501       -  is-alphabetical@2.0.1: {}
 5502       -
 5503       -  is-alphanumerical@2.0.1:
 5504       -    dependencies:
 5505       -      is-alphabetical: 2.0.1
 5506       -      is-decimal: 2.0.1
 5507       -
 5508  5325    is-arrayish@0.2.1: {}
 5509  5326  
 5510       -  is-decimal@2.0.1: {}
 5511       -
 5512  5327    is-docker@2.2.1: {}
 5513  5328  
 5514  5329    is-docker@3.0.0: {}
@@ -5520,8 +5335,6 @@ snapshots:
 5521  5336      dependencies:
 5522  5337        is-extglob: 2.1.1
 5523  5338  
 5524       -  is-hexadecimal@2.0.1: {}
 5525       -
 5526  5339    is-in-ssh@1.0.0: {}
 5527  5340  
 5528  5341    is-inside-container@1.0.0:
@@ -5576,7 +5389,7 @@ snapshots:
 5577  5390      dependencies:
 5578  5391        argparse: 2.0.1
 5579  5392  
 5580       -  jsdom@28.1.0(supports-color@10.2.2):
       5393 +  jsdom@28.1.0:
 5581  5394      dependencies:
 5582  5395        '@acemir/cssom': 0.9.31
 5583  5396        '@asamuzakjp/dom-selector': 6.8.1
@@ -5586,8 +5399,8 @@ snapshots:
 5587  5400        data-urls: 7.0.0
 5588  5401        decimal.js: 10.6.0
 5589  5402        html-encoding-sniffer: 6.0.0
 5590       -      http-proxy-agent: 7.0.2(supports-color@10.2.2)
 5591       -      https-proxy-agent: 7.0.6(supports-color@10.2.2)
       5403 +      http-proxy-agent: 7.0.2
       5404 +      https-proxy-agent: 7.0.6
 5592  5405        is-potential-custom-element-name: 1.0.1
 5593  5406        parse5: 8.0.1
 5594  5407        saxes: 6.0.0
@@ -5691,11 +5504,6 @@ snapshots:
 5692  5505        chalk: 5.6.2
 5693  5506        is-unicode-supported: 1.3.0
 5694  5507  
 5695       -  lowlight@1.20.0:
 5696       -    dependencies:
 5697       -      fault: 1.0.4
 5698       -      highlight.js: 10.7.3
 5699       -
 5700  5508    lru-cache@11.5.1: {}
 5701  5509  
 5702  5510    lru-cache@5.1.1:
@@ -5870,16 +5678,6 @@ snapshots:
 5871  5679      dependencies:
 5872  5680        callsites: 3.1.0
 5873  5681  
 5874       -  parse-entities@4.0.2:
 5875       -    dependencies:
 5876       -      '@types/unist': 2.0.11
 5877       -      character-entities-legacy: 3.0.0
 5878       -      character-reference-invalid: 2.0.1
 5879       -      decode-named-character-reference: 1.3.0
 5880       -      is-alphanumerical: 2.0.1
 5881       -      is-decimal: 2.0.1
 5882       -      is-hexadecimal: 2.0.1
 5883       -
 5884  5682    parse-json@5.2.0:
 5885  5683      dependencies:
 5886  5684        '@babel/code-frame': 7.29.7
@@ -5951,15 +5749,11 @@ snapshots:
 5952  5750      dependencies:
 5953  5751        parse-ms: 4.0.0
 5954  5752  
 5955       -  prismjs@1.30.0: {}
 5956       -
 5957  5753    prompts@2.4.2:
 5958  5754      dependencies:
 5959  5755        kleur: 3.0.3
 5960  5756        sisteransi: 1.0.5
 5961  5757  
 5962       -  property-information@7.2.0: {}
 5963       -
 5964  5758    proxy-addr@2.0.7:
 5965  5759      dependencies:
 5966  5760        forwarded: 0.2.0
@@ -5990,16 +5784,6 @@ snapshots:
 5991  5785  
 5992  5786    react-is@17.0.2: {}
 5993  5787  
 5994       -  react-syntax-highlighter@16.1.1(react@19.2.7):
 5995       -    dependencies:
 5996       -      '@babel/runtime': 7.29.7
 5997       -      highlight.js: 10.7.3
 5998       -      highlightjs-vue: 1.0.0
 5999       -      lowlight: 1.20.0
 6000       -      prismjs: 1.30.0
 6001       -      react: 19.2.7
 6002       -      refractor: 5.0.0
 6003       -
 6004  5788    react@19.2.7: {}
 6005  5789  
 6006  5790    readdirp@5.0.0: {}
@@ -6012,13 +5796,6 @@ snapshots:
 6013  5797        tiny-invariant: 1.3.3
 6014  5798        tslib: 2.8.1
 6015  5799  
 6016       -  refractor@5.0.0:
 6017       -    dependencies:
 6018       -      '@types/hast': 3.0.5
 6019       -      '@types/prismjs': 1.26.6
 6020       -      hastscript: 9.0.1
 6021       -      parse-entities: 4.0.2
 6022       -
 6023  5800    require-directory@2.1.1: {}
 6024  5801  
 6025  5802    require-from-string@2.0.2: {}
@@ -6057,9 +5834,9 @@ snapshots:
 6058  5835  
 6059  5836    rou3@0.8.1: {}
 6060  5837  
 6061       -  router@2.2.0(supports-color@10.2.2):
       5838 +  router@2.2.0:
 6062  5839      dependencies:
 6063       -      debug: 4.4.3(supports-color@10.2.2)
       5840 +      debug: 4.4.3
 6064  5841        depd: 2.0.0
 6065  5842        is-promise: 4.0.0
 6066  5843        parseurl: 1.3.3
@@ -6085,9 +5862,9 @@ snapshots:
 6086  5863  
 6087  5864    semver@7.8.5: {}
 6088  5865  
 6089       -  send@1.2.1(supports-color@10.2.2):
       5866 +  send@1.2.1:
 6090  5867      dependencies:
 6091       -      debug: 4.4.3(supports-color@10.2.2)
       5868 +      debug: 4.4.3
 6092  5869        encodeurl: 2.0.0
 6093  5870        escape-html: 1.0.3
 6094  5871        etag: 1.8.1
@@ -6105,33 +5882,27 @@ snapshots:
 6106  5883      dependencies:
 6107  5884        seroval: 1.5.4
 6108  5885  
 6109       -  seroval-plugins@1.6.2(seroval@1.6.2):
 6110       -    dependencies:
 6111       -      seroval: 1.6.2
 6112       -
 6113  5886    seroval@1.5.4: {}
 6114  5887  
 6115       -  seroval@1.6.2: {}
 6116       -
 6117       -  serve-static@2.2.1(supports-color@10.2.2):
       5888 +  serve-static@2.2.1:
 6118  5889      dependencies:
 6119  5890        encodeurl: 2.0.0
 6120  5891        escape-html: 1.0.3
 6121  5892        parseurl: 1.3.3
 6122       -      send: 1.2.1(supports-color@10.2.2)
       5893 +      send: 1.2.1
 6123  5894      transitivePeerDependencies:
 6124  5895        - supports-color
 6125  5896  
 6126  5897    setprototypeof@1.2.0: {}
 6127  5898  
 6128       -  shadcn@4.12.0(supports-color@10.2.2)(typescript@6.0.3):
       5899 +  shadcn@4.12.0(typescript@6.0.3):
 6129  5900      dependencies:
 6130       -      '@babel/core': 7.29.7(supports-color@10.2.2)
       5901 +      '@babel/core': 7.29.7
 6131  5902        '@babel/parser': 7.29.7
 6132       -      '@babel/plugin-transform-typescript': 7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)
 6133       -      '@babel/preset-typescript': 7.29.7(@babel/core@7.29.7(supports-color@10.2.2))(supports-color@10.2.2)
       5903 +      '@babel/plugin-transform-typescript': 7.29.7(@babel/core@7.29.7)
       5904 +      '@babel/preset-typescript': 7.29.7(@babel/core@7.29.7)
 6134  5905        '@dotenvx/dotenvx': 1.75.1
 6135       -      '@modelcontextprotocol/sdk': 1.29.0(supports-color@10.2.2)(zod@3.25.76)
       5906 +      '@modelcontextprotocol/sdk': 1.29.0(zod@3.25.76)
 6136  5907        '@types/validate-npm-package-name': 4.0.2
 6137  5908        browserslist: 4.28.4
 6138  5909        commander: 14.0.3
@@ -6256,8 +6027,6 @@ snapshots:
 6257  6028  
 6258  6029    source-map@0.7.6: {}
 6259  6030  
 6260       -  space-separated-tokens@2.0.2: {}
 6261       -
 6262  6031    srvx@0.11.17: {}
 6263  6032  
 6264  6033    stackback@0.0.2: {}
@@ -6427,7 +6196,7 @@ snapshots:
 6428  6197      optionalDependencies:
 6429  6198        vite: 8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0)
 6430  6199  
 6431       -  vitest@4.1.9(@types/node@22.20.0)(jsdom@28.1.0(supports-color@10.2.2))(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0)):
       6200 +  vitest@4.1.9(@types/node@22.20.0)(jsdom@28.1.0)(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0)):
 6432  6201      dependencies:
 6433  6202        '@vitest/expect': 4.1.9
 6434  6203        '@vitest/mocker': 4.1.9(vite@8.1.0(@types/node@22.20.0)(esbuild@0.28.1)(jiti@2.7.0))
@@ -6451,7 +6220,7 @@ snapshots:
 6452  6221        why-is-node-running: 2.3.0
 6453  6222      optionalDependencies:
 6454  6223        '@types/node': 22.20.0
 6455       -      jsdom: 28.1.0(supports-color@10.2.2)
       6224 +      jsdom: 28.1.0
 6456  6225      transitivePeerDependencies:
 6457  6226        - msw
 6458  6227  

```
