USE fleetbase;

    -- Create company if not exists
    INSERT INTO companies (uuid, public_id, name, created_at, updated_at, slug)
    SELECT 'c57fc9eb-bf68-4bd8-83b3-ac054ee12c2d', 'com_kelava', 'Kelava Logistics', NOW(), NOW(), 'kelava-logistics'
    WHERE NOT EXISTS (SELECT 1 FROM companies LIMIT 1);
    
SET @company_uuid = (SELECT uuid FROM companies LIMIT 1);

        INSERT INTO drivers (uuid, public_id, internal_id, company_uuid, created_at, updated_at, location)
        SELECT 'f6145ea7-b4ff-4041-a301-b06bdb1ba892', 'driver_392', '392', @company_uuid, '2026-02-05 11:15:16', '2026-02-05 11:15:16', ST_GeomFromText('POINT(0 0)')
        WHERE NOT EXISTS (SELECT 1 FROM drivers WHERE internal_id = '392');
        
SET @d_uuid = (SELECT uuid FROM drivers WHERE internal_id = '392' LIMIT 1);

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('0dd8fe5f-a1f2-48d6-a705-b22fd46e75af', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258465183138264 112.75217922927733)'), '2026-02-05 11:05:16', '2026-02-05 11:05:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('7661afdd-bb26-4c2a-82a2-97e6364d0b55', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258270237083349 112.75218745809578)'), '2026-02-05 11:06:16', '2026-02-05 11:06:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('3c066e8e-60bf-435d-8f83-d4fe8d4b2a20', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.259035986927027 112.75165989325069)'), '2026-02-05 11:07:16', '2026-02-05 11:07:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('cb1a994c-d408-4031-b17a-a509484a50b9', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.25967052118577 112.75253492936925)'), '2026-02-05 11:08:16', '2026-02-05 11:08:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('5365fb78-397f-4a8e-8793-b4e1905bfffc', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.2598707202156545 112.753361272555)'), '2026-02-05 11:09:16', '2026-02-05 11:09:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('a64fb019-e3ad-42f5-b2ac-6972ffe297f7', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.260348042332622 112.7524615625597)'), '2026-02-05 11:10:16', '2026-02-05 11:10:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('556574c0-0003-45af-b1c4-d3450163ec61', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.260650727255295 112.75276835169697)'), '2026-02-05 11:11:16', '2026-02-05 11:11:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('0c47d65a-1fc2-4c2a-bda4-8a18f4f7bb9b', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.26113793281813 112.75245636840353)'), '2026-02-05 11:12:16', '2026-02-05 11:12:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('bf192500-1ffc-48b6-97ed-0dae7cc68371', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.260183187393702 112.75332244235113)'), '2026-02-05 11:13:16', '2026-02-05 11:13:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('cd3d2b7a-f0df-4e48-8303-c12c2112c3e7', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.261072554888866 112.75370872067133)'), '2026-02-05 11:14:16', '2026-02-05 11:14:16');
            

        INSERT INTO drivers (uuid, public_id, internal_id, company_uuid, created_at, updated_at, location)
        SELECT 'cf2b6eb1-8f4f-4fb2-b4c4-3c74124da72b', 'driver_396', '396', @company_uuid, '2026-02-05 11:15:16', '2026-02-05 11:15:16', ST_GeomFromText('POINT(0 0)')
        WHERE NOT EXISTS (SELECT 1 FROM drivers WHERE internal_id = '396');
        
SET @d_uuid = (SELECT uuid FROM drivers WHERE internal_id = '396' LIMIT 1);

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('cb77470e-887e-4f46-9e32-d21cf5ad0286', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257152295238784 112.75137576379291)'), '2026-02-05 11:05:16', '2026-02-05 11:05:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('88548fef-827e-46c9-ac95-5d3ad0663802', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256856101796953 112.75108130898673)'), '2026-02-05 11:06:16', '2026-02-05 11:06:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('34976941-8300-47a5-8ea0-564388bd7eb4', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.2566861823615065 112.75154234222289)'), '2026-02-05 11:07:16', '2026-02-05 11:07:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('08b35e49-fa3f-43c8-8b2e-d1fbfbf9d2ef', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255940245640507 112.75112082772637)'), '2026-02-05 11:08:16', '2026-02-05 11:08:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('7355e0cb-959b-470e-9283-c98661fb93d1', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.25662216040679 112.75194077211033)'), '2026-02-05 11:09:16', '2026-02-05 11:09:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('6ea42458-a575-43b4-8a49-7572b44a1383', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257485445647571 112.75119910794383)'), '2026-02-05 11:10:16', '2026-02-05 11:10:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('20fcaf96-6c10-4b65-b0e5-78c38c954467', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.25707992043106 112.75193381014333)'), '2026-02-05 11:11:16', '2026-02-05 11:11:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('4053b3b9-1ef8-4725-a16d-880821f4aae5', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.2570282296253215 112.75118408787989)'), '2026-02-05 11:12:16', '2026-02-05 11:12:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('0290ef25-7589-4811-b5cc-c7aa4f851b1f', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257348522155905 112.75072285461948)'), '2026-02-05 11:13:16', '2026-02-05 11:13:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('c5cd8d72-d5e7-402b-85a5-4e8e25c77118', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256797668683987 112.75104839824458)'), '2026-02-05 11:14:16', '2026-02-05 11:14:16');
            

        INSERT INTO drivers (uuid, public_id, internal_id, company_uuid, created_at, updated_at, location)
        SELECT 'bee8dd89-7298-4699-b791-4fd3afd38a7f', 'driver_403', '403', @company_uuid, '2026-02-05 11:15:16', '2026-02-05 11:15:16', ST_GeomFromText('POINT(0 0)')
        WHERE NOT EXISTS (SELECT 1 FROM drivers WHERE internal_id = '403');
        
SET @d_uuid = (SELECT uuid FROM drivers WHERE internal_id = '403' LIMIT 1);

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('eb6bb03f-9d2b-4b4a-b963-b0311bd9d166', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.2584418208572545 112.75266842040492)'), '2026-02-05 11:05:16', '2026-02-05 11:05:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('70720f08-d1d5-4611-be97-a5e6dee0ddd4', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257600430352322 112.75298615682398)'), '2026-02-05 11:06:16', '2026-02-05 11:06:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('4a5ddb9d-b6ae-4cfa-8fa4-967f256936e3', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256707811101305 112.75380174492943)'), '2026-02-05 11:07:16', '2026-02-05 11:07:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('3983f793-15bb-4ac2-a9be-990625312094', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256473121774013 112.7541195095417)'), '2026-02-05 11:08:16', '2026-02-05 11:08:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('eb0d9380-6c2b-4307-b8d7-df8555fffe68', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256026369187784 112.75502145255099)'), '2026-02-05 11:09:16', '2026-02-05 11:09:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('23afd671-6ad7-4263-b1a1-74ef288893be', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255609815534126 112.75599222832315)'), '2026-02-05 11:10:16', '2026-02-05 11:10:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('990e2077-2efd-4b13-93c1-8b3b552b4ae4', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255825406003669 112.756787701124)'), '2026-02-05 11:11:16', '2026-02-05 11:11:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('ed0adb58-6dae-419d-8c33-b571eac8499d', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255920175850998 112.75618399680891)'), '2026-02-05 11:12:16', '2026-02-05 11:12:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('79f2f421-41aa-4190-8b5a-d69e08d03d8d', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.2553134347188415 112.75638115274215)'), '2026-02-05 11:13:16', '2026-02-05 11:13:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('5c7bd078-82bb-4a16-848a-9a345d018e88', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255526645715333 112.75665830383915)'), '2026-02-05 11:14:16', '2026-02-05 11:14:16');
            

        INSERT INTO drivers (uuid, public_id, internal_id, company_uuid, created_at, updated_at, location)
        SELECT '9536556a-99b4-4ec1-bb16-6231dc092c00', 'driver_399', '399', @company_uuid, '2026-02-05 11:15:16', '2026-02-05 11:15:16', ST_GeomFromText('POINT(0 0)')
        WHERE NOT EXISTS (SELECT 1 FROM drivers WHERE internal_id = '399');
        
SET @d_uuid = (SELECT uuid FROM drivers WHERE internal_id = '399' LIMIT 1);

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('745c0783-b71d-4f22-b2ba-2393c1d1c0fa', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257583909633511 112.75137162688331)'), '2026-02-05 11:05:16', '2026-02-05 11:05:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('3e21ac75-56e9-4a6a-b6c0-839271e7901a', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258020449282837 112.75148639114653)'), '2026-02-05 11:06:16', '2026-02-05 11:06:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('bd5011c9-fe60-4046-a1b1-a8388ec8e495', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257410097997184 112.75137203884286)'), '2026-02-05 11:07:16', '2026-02-05 11:07:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('e3cc4765-a4fb-4d01-88ac-cfd108606e87', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257516263721392 112.75175391108255)'), '2026-02-05 11:08:16', '2026-02-05 11:08:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('24161c8e-6629-408b-be5f-e64d511543e7', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257826820450457 112.75075853172754)'), '2026-02-05 11:09:16', '2026-02-05 11:09:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('9264391a-dda6-4f87-a0aa-7532a3657fec', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257515528233181 112.75057243086967)'), '2026-02-05 11:10:16', '2026-02-05 11:10:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('f2db6fff-2663-4759-85b9-eb049fe2f500', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256648161090408 112.75071189172934)'), '2026-02-05 11:11:16', '2026-02-05 11:11:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('ef929d80-ca97-4c88-b100-c56db93ddb78', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255831289667802 112.75111415171602)'), '2026-02-05 11:12:16', '2026-02-05 11:12:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('1e67df6c-1c1b-44e7-b6e9-bdee78b3928a', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255714124336277 112.75105378513604)'), '2026-02-05 11:13:16', '2026-02-05 11:13:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('9fa8feed-fc69-4a8b-b6ff-87ecff381b49', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255905566403624 112.75009515427358)'), '2026-02-05 11:14:16', '2026-02-05 11:14:16');
            

        INSERT INTO drivers (uuid, public_id, internal_id, company_uuid, created_at, updated_at, location)
        SELECT '8f8328de-80bc-4f17-bf66-3ac1741a981a', 'driver_379', '379', @company_uuid, '2026-02-05 11:15:16', '2026-02-05 11:15:16', ST_GeomFromText('POINT(0 0)')
        WHERE NOT EXISTS (SELECT 1 FROM drivers WHERE internal_id = '379');
        
SET @d_uuid = (SELECT uuid FROM drivers WHERE internal_id = '379' LIMIT 1);

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('aff8c770-345a-4f8e-8ded-fe309f226003', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258184730995001 112.75116901867241)'), '2026-02-05 11:05:16', '2026-02-05 11:05:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('b38fb0ec-132c-4362-9e05-f00ba05175cd', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.259159679908647 112.75095284219869)'), '2026-02-05 11:06:16', '2026-02-05 11:06:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('72dfbed6-d4ff-4ad0-9cd0-91183f4c777e', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258998906612535 112.75079622449465)'), '2026-02-05 11:07:16', '2026-02-05 11:07:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('0ca695b2-2966-4225-91e0-bfe41a56b762', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258752478049313 112.7505325773638)'), '2026-02-05 11:08:16', '2026-02-05 11:08:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('c382fdc2-c442-42b1-afe4-b92e536e2a28', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.259573236944996 112.74989039954319)'), '2026-02-05 11:09:16', '2026-02-05 11:09:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('db880419-e700-415c-83da-a1f1222da106', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.2602286043272795 112.74950229156794)'), '2026-02-05 11:10:16', '2026-02-05 11:10:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('1a8dee77-89b1-42a5-88cd-ab5e6651a562', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.259662649030483 112.74979118962968)'), '2026-02-05 11:11:16', '2026-02-05 11:11:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('2dd1b72c-f68d-4ce6-83e3-5d7c7dde8980', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.259491779688418 112.74926749920998)'), '2026-02-05 11:12:16', '2026-02-05 11:12:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('d4a2e1ab-00e7-4de5-800c-b9b87f83255e', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.260458509555626 112.74829031158896)'), '2026-02-05 11:13:16', '2026-02-05 11:13:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('5182da26-c59f-4dc4-bda7-21eb7229baa0', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.260279343134371 112.74925700096534)'), '2026-02-05 11:14:16', '2026-02-05 11:14:16');
            

        INSERT INTO drivers (uuid, public_id, internal_id, company_uuid, created_at, updated_at, location)
        SELECT 'a167072b-52b1-482d-bd82-3b6215ebd939', 'driver_383', '383', @company_uuid, '2026-02-05 11:15:16', '2026-02-05 11:15:16', ST_GeomFromText('POINT(0 0)')
        WHERE NOT EXISTS (SELECT 1 FROM drivers WHERE internal_id = '383');
        
SET @d_uuid = (SELECT uuid FROM drivers WHERE internal_id = '383' LIMIT 1);

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('856abf70-35ba-4ddf-a8f2-b539b6f7cdda', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257190296916666 112.75245542254294)'), '2026-02-05 11:05:16', '2026-02-05 11:05:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('835761b7-6c84-48f7-8638-ef7b06083f25', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256987146988208 112.75201468787333)'), '2026-02-05 11:06:16', '2026-02-05 11:06:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('8d847d34-c35a-4c35-89a7-ef0d18f7ce8d', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257175551104403 112.75114319862116)'), '2026-02-05 11:07:16', '2026-02-05 11:07:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('47d75c90-50c1-4140-8205-ebe3d030dfe1', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257511935618737 112.75126157546703)'), '2026-02-05 11:08:16', '2026-02-05 11:08:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('bfeedee4-de83-45ef-bd1d-7762210abbd9', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256663746933052 112.75073557515452)'), '2026-02-05 11:09:16', '2026-02-05 11:09:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('a1904751-393b-43cf-ae0c-506577d5b094', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.25647575462628 112.75098987098674)'), '2026-02-05 11:10:16', '2026-02-05 11:10:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('9c009feb-8edb-43cb-912c-192e2277bd57', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256723173333109 112.75066096098013)'), '2026-02-05 11:11:16', '2026-02-05 11:11:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('e5389179-7859-4cd0-886c-0a9416276076', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256867940543337 112.750238938985)'), '2026-02-05 11:12:16', '2026-02-05 11:12:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('1e7cf8fb-3ed7-4e3c-a527-d4133033f9c5', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256929895072052 112.74958581960992)'), '2026-02-05 11:13:16', '2026-02-05 11:13:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('850f3ea3-eff0-4600-987a-7ee8a11d16d1', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256851144900742 112.74980279710624)'), '2026-02-05 11:14:16', '2026-02-05 11:14:16');
            

        INSERT INTO drivers (uuid, public_id, internal_id, company_uuid, created_at, updated_at, location)
        SELECT '141cb620-29a3-41c9-8ac7-353abc8647df', 'driver_385', '385', @company_uuid, '2026-02-05 11:15:16', '2026-02-05 11:15:16', ST_GeomFromText('POINT(0 0)')
        WHERE NOT EXISTS (SELECT 1 FROM drivers WHERE internal_id = '385');
        
SET @d_uuid = (SELECT uuid FROM drivers WHERE internal_id = '385' LIMIT 1);

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('e1fd3546-a257-49e4-9f52-246c815d7ef6', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.2569605442110605 112.75122593470624)'), '2026-02-05 11:05:16', '2026-02-05 11:05:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('41145cd4-972e-4713-b0ba-2ca08606b986', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255995001557495 112.75152094427158)'), '2026-02-05 11:06:16', '2026-02-05 11:06:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('bb2ab4b6-f879-444c-9097-35f69c490669', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256467233316028 112.75229579186109)'), '2026-02-05 11:07:16', '2026-02-05 11:07:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('84ee75f0-ed0a-46bb-a4da-0612d526116e', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256194413931859 112.75279921362988)'), '2026-02-05 11:08:16', '2026-02-05 11:08:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('038734a9-a6eb-4934-86c1-339420706cf2', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256020726400395 112.75359502510916)'), '2026-02-05 11:09:16', '2026-02-05 11:09:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('42975dfe-7163-4cca-a698-56b60b2945a1', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255680850758871 112.75307832144993)'), '2026-02-05 11:10:16', '2026-02-05 11:10:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('80be604e-ecff-4942-9835-fa32f897e7d1', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255048738120525 112.75374718292517)'), '2026-02-05 11:11:16', '2026-02-05 11:11:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('88a2a59b-0cc8-43ca-9d8b-685663b3363f', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255826190905455 112.75295021844647)'), '2026-02-05 11:12:16', '2026-02-05 11:12:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('8163f030-13dc-4a77-a7d8-1756dbe9ff13', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256067258071019 112.75374223434886)'), '2026-02-05 11:13:16', '2026-02-05 11:13:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('e9246f90-5604-4d23-8e97-f7e4558d2980', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255691261532136 112.75324661065179)'), '2026-02-05 11:14:16', '2026-02-05 11:14:16');
            

        INSERT INTO drivers (uuid, public_id, internal_id, company_uuid, created_at, updated_at, location)
        SELECT 'db66e419-9f9e-4ffd-ad29-ea52e3a4e903', 'driver_386', '386', @company_uuid, '2026-02-05 11:15:16', '2026-02-05 11:15:16', ST_GeomFromText('POINT(0 0)')
        WHERE NOT EXISTS (SELECT 1 FROM drivers WHERE internal_id = '386');
        
SET @d_uuid = (SELECT uuid FROM drivers WHERE internal_id = '386' LIMIT 1);

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('eba59abe-e8ba-463d-9df5-dadd6392184c', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257785488673924 112.75265501974887)'), '2026-02-05 11:05:16', '2026-02-05 11:05:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('d1be1661-a7cd-413f-ac91-7ad9421e796d', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258336454142804 112.75257465793837)'), '2026-02-05 11:06:16', '2026-02-05 11:06:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('71af80f6-05eb-4a91-ac69-928674f2ba00', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258498435315332 112.75238240686075)'), '2026-02-05 11:07:16', '2026-02-05 11:07:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('d89002cd-d642-45f3-8737-5aa33e5e30da', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257801156403827 112.75231402452569)'), '2026-02-05 11:08:16', '2026-02-05 11:08:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('6996e697-1f1b-4df4-b75f-53887d6b23e5', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258542438119114 112.75176961592322)'), '2026-02-05 11:09:16', '2026-02-05 11:09:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('a845f05c-b440-4d89-89bc-203cebc12abd', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258634788976257 112.7508974888687)'), '2026-02-05 11:10:16', '2026-02-05 11:10:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('baba606f-9199-4016-b959-8eabc57fb43a', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258274218320012 112.75157438384623)'), '2026-02-05 11:11:16', '2026-02-05 11:11:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('c6a59be8-0a95-4d35-827a-72f52933b742', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258074595061672 112.75163767897115)'), '2026-02-05 11:12:16', '2026-02-05 11:12:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('ef5301fc-77a3-4972-8dc2-191938b68086', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.259073420405586 112.75213559827245)'), '2026-02-05 11:13:16', '2026-02-05 11:13:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('e90c24a3-b28e-4d6a-a34d-726022a00d27', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.259070952264873 112.7516646270804)'), '2026-02-05 11:14:16', '2026-02-05 11:14:16');
            

        INSERT INTO drivers (uuid, public_id, internal_id, company_uuid, created_at, updated_at, location)
        SELECT 'd283ddda-3820-4101-9a38-1dfc0241468f', 'driver_389', '389', @company_uuid, '2026-02-05 11:15:16', '2026-02-05 11:15:16', ST_GeomFromText('POINT(0 0)')
        WHERE NOT EXISTS (SELECT 1 FROM drivers WHERE internal_id = '389');
        
SET @d_uuid = (SELECT uuid FROM drivers WHERE internal_id = '389' LIMIT 1);

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('ac7416c7-f3bf-47ec-b702-216d2d1805c2', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257030594377957 112.75224789217457)'), '2026-02-05 11:05:16', '2026-02-05 11:05:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('42a41654-d587-4682-83e1-c0cac26ba451', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257041816362601 112.75274055897317)'), '2026-02-05 11:06:16', '2026-02-05 11:06:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('f104f25d-305d-478c-9190-875a4e40fc5a', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256310503665694 112.75242785883663)'), '2026-02-05 11:07:16', '2026-02-05 11:07:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('30f91f40-0328-4833-83b8-f93b07ff29ac', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256045755140726 112.75222207083773)'), '2026-02-05 11:08:16', '2026-02-05 11:08:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('524a3027-6077-4a5a-8acb-8e90a016c7f8', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255210836682324 112.75247024868914)'), '2026-02-05 11:09:16', '2026-02-05 11:09:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('a4116a23-8b65-4fd4-a341-c1de5a9fd8be', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.2549607292586895 112.75335243372157)'), '2026-02-05 11:10:16', '2026-02-05 11:10:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('66f25d8c-ac1a-4a79-bbc6-c9e0cc0b8c4c', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255373558146871 112.75291985482302)'), '2026-02-05 11:11:16', '2026-02-05 11:11:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('540ed085-81c8-499a-855a-3202ef676ce2', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255192082120099 112.7538840235787)'), '2026-02-05 11:12:16', '2026-02-05 11:12:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('a68bab36-6948-4906-9e8e-3a0a07451c18', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255997027618985 112.75457349379035)'), '2026-02-05 11:13:16', '2026-02-05 11:13:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('81a82143-9285-4607-8212-1c4cf6adc75b', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.2556455234602435 112.75403786273056)'), '2026-02-05 11:14:16', '2026-02-05 11:14:16');
            

        INSERT INTO drivers (uuid, public_id, internal_id, company_uuid, created_at, updated_at, location)
        SELECT '0af94b5a-ff2f-4cbc-80c2-5e59bfbdfd3c', 'driver_390', '390', @company_uuid, '2026-02-05 11:15:16', '2026-02-05 11:15:16', ST_GeomFromText('POINT(0 0)')
        WHERE NOT EXISTS (SELECT 1 FROM drivers WHERE internal_id = '390');
        
SET @d_uuid = (SELECT uuid FROM drivers WHERE internal_id = '390' LIMIT 1);

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('441329fd-542b-4f4b-9813-a78a355fcf9c', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.258035679493327 112.7530662927587)'), '2026-02-05 11:05:16', '2026-02-05 11:05:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('85c838fb-6218-4cdd-8c53-2e6eb65d152c', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.257291802488868 112.75227710806062)'), '2026-02-05 11:06:16', '2026-02-05 11:06:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('4128cded-8dca-47c6-ac99-13a61e0f795c', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256673915296305 112.75233480907141)'), '2026-02-05 11:07:16', '2026-02-05 11:07:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('6174f4b1-4cb4-4756-a067-9d10235f61dd', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.256895162934513 112.7527739984112)'), '2026-02-05 11:08:16', '2026-02-05 11:08:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('caaade55-ef9b-4bd0-a7e8-d693a18e0c24', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.2570332203881325 112.75218382138259)'), '2026-02-05 11:09:16', '2026-02-05 11:09:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('4a20db11-c352-45a6-bb7f-1909767e5dd6', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.25645882554451 112.75164481510302)'), '2026-02-05 11:10:16', '2026-02-05 11:10:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('c5eb7240-f285-4e53-b299-9d7c3d790ab5', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.25663000734903 112.75096942430021)'), '2026-02-05 11:11:16', '2026-02-05 11:11:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('4df4c851-ba63-4fbe-bea5-f1a32dc5e62b', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.2563489795372655 112.75116245056913)'), '2026-02-05 11:12:16', '2026-02-05 11:12:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('b3e7124d-ceba-499a-97c6-5df37d62af10', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.25571955246121 112.75206613328022)'), '2026-02-05 11:13:16', '2026-02-05 11:13:16');
            

            INSERT INTO positions (uuid, subject_uuid, subject_type, coordinates, created_at, updated_at)
            VALUES ('92af4019-59ae-419a-9e7f-303f1596fd78', @d_uuid, 'driver', ST_GeomFromText('POINT(-7.255406930226948 112.7517969868343)'), '2026-02-05 11:14:16', '2026-02-05 11:14:16');
            