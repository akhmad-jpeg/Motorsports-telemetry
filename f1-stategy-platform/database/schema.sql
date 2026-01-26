CREATE DATABASE F1_strategy;
USE F1_strategy;

CREATE TABLE sessions (
    session_id INT AUTO_INCREMENT PRIMARY KEY,
    track_name VARCHAR(50),
    session_type ENUM('Race','Qualifying','Practice'),
    weather VARCHAR(20),
    date DATE,
    time TIME
);

CREATE TABLE laps (
    lap_id INT AUTO_INCREMENT PRIMARY KEY,
    session_id INT,
    lap_number INT,
    lap_time_ms INT,
    tyre_compound ENUM('Hypersoft', 'Ultrasoft', 'Supersoft', 'Soft','Medium','Hard', 'Superhard', 'Intermediate','Wet'),
    tyre_age INT,
    fuel_load FLOAT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE telemetry (
    telemetry_id INT AUTO_INCREMENT PRIMARY KEY,
    lap_id INT,
    speed INT,
    throttle FLOAT,
    brake FLOAT,
    gear INT,
    rpm INT,
    drs BOOLEAN,
    FOREIGN KEY (lap_id) REFERENCES laps(lap_id)
);

CREATE TABLE strategy_events (
    event_id INT AUTO_INCREMENT PRIMARY KEY,
    lap_id INT,
    event_type ENUM('PitStop','SafetyCar','VSC', 'RedFlag'),
    duration_sec FLOAT,
    FOREIGN KEY (lap_id) REFERENCES laps(lap_id)
);