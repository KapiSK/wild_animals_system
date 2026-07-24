void setup() {
  Serial.begin(115200);
  // ADC resolution to 12 bits (0-4095)
  analogReadResolution(12);
}

void loop() {
  // Read analog value from GPIO 5
  int sensorValue = analogRead(5);
  // Convert the analog value to voltage (assuming 3.3V reference)
  float voltage = sensorValue * (3.3 / 4095.0);

  Serial.print("GPIO 5 Value: ");
  Serial.print(sensorValue);
  Serial.print(" | Voltage: ");
  Serial.println(voltage);

  delay(500);
}
