/**
 * Copyright (C) Bosch Sensortec GmbH. All Rights Reserved. Confidential.
 *
 * Disclaimer
 *
 * Common:
 * Bosch Sensortec products are developed for the consumer goods industry. They may only be used
 * within the parameters of the respective valid product data sheet. Bosch Sensortec products are
 * provided with the express understanding that there is no warranty of fitness for a particular purpose.
 * They are not fit for use in life-sustaining, safety or security sensitive systems or any system or device
 * that may lead to bodily harm or property damage if the system or device malfunctions. In addition,
 * Bosch Sensortec products are not fit for use in products which interact with motor vehicle systems.
 * The resale and/or use of products are at the purchaser's own risk and his own responsibility. The
 * examination of fitness for the intended use is the sole responsibility of the Purchaser.
 *
 * The purchaser shall indemnify Bosch Sensortec from all third party claims, including any claims for
 * incidental, or consequential damages, arising from any product use not covered by the parameters of
 * the respective valid product data sheet or not approved by Bosch Sensortec and reimburse Bosch
 * Sensortec for all costs in connection with such claims.
 *
 * The purchaser must monitor the market for the purchased products, particularly with regard to
 * product safety and inform Bosch Sensortec without delay of all security relevant incidents.
 *
 * Engineering Samples are marked with an asterisk (*) or (e). Samples may vary from the valid
 * technical specifications of the product series. They are therefore not intended or fit for resale to third
 * parties or for use in end products. Their sole purpose is internal client testing. The testing of an
 * engineering sample may in no way replace the testing of a product series. Bosch Sensortec
 * assumes no liability for the use of engineering samples. By accepting the engineering samples, the
 * Purchaser agrees to indemnify Bosch Sensortec from all claims arising from the use of engineering
 * samples.
 *
 * Special:
 * This software module (hereinafter called "Software") and any information on application-sheets
 * (hereinafter called "Information") is provided free of charge for the sole purpose to support your
 * application work. The Software and Information is subject to the following terms and conditions:
 *
 * The Software is specifically designed for the exclusive use for Bosch Sensortec products by
 * personnel who have special experience and training. Do not use this Software if you do not have the
 * proper experience or training.
 *
 * This Software package is provided `` as is `` and without any expressed or implied warranties,
 * including without limitation, the implied warranties of merchantability and fitness for a particular
 * purpose.
 *
 * Bosch Sensortec and their representatives and agents deny any liability for the functional impairment
 * of this Software in terms of fitness, performance and safety. Bosch Sensortec and their
 * representatives and agents shall not be liable for any direct or indirect damages or injury, except as
 * otherwise stipulated in mandatory applicable law.
 *
 * The Information provided is believed to be accurate and reliable. Bosch Sensortec assumes no
 * responsibility for the consequences of use of such Information nor for any infringement of patents or
 * other rights of third parties which may result from its use. No license is granted by implication or
 * otherwise under any patent or patent rights of Bosch. Specifications mentioned in the Information are
 * subject to change without notice.
 *
 * It is not allowed to deliver the source code of the Software to any third party without permission of
 * Bosch Sensortec.
 *
 */

const helpContentEUHtml = `<div id="helpContent" class="tab">
                                <h2 id="helpTitle"> Welcome to BMV080 Web App</h2>
                                <div class="explanation">

                                    Just getting started? Let's take a look at some of the key features of this app.
                                    <br><br>
                                    This app is the first of its kind, allowing real-time measurement of the particulate matter (PM) you are exposed to.
                                    <br><br>
                                    Particulate matter consists of microscopic solids or liquid droplets small enough to be inhaled and cause serious health issues. Small particles – particularly those smaller than or equal to 1µm (PM1), 2.5µm (PM2.5), and 10µm (PM10) – are major contributors to air pollution. PM1 and PM2.5 can penetrate deep into the lungs and even enter the bloodstream, while PM10 primarily affects the upper respiratory system, potentially leading to long-term health effects.
                                    <br><br>
                                    This app allows you to evaluate the <b>BMV080</b> for integration into your future designs, helping to enable solutions that support healthier environments and empower users to take meaningful action.
                                    <br><br>
                                    <div id="lungsImageContainer">
                                        <img id="lungsImage" src="./bmv080/img/lungs.gif" alt="lung">
                                    </div>
                                </div>
                                <h2>Performing a measurement</h2>
                                <div class="explanation">
                                    When measuring PM the sensor reading is shown in either the Gauge (current value) in the "Current Reading" section or in the Time Domain diagram (most recent values) in the "Past Readings" section.
                                    <br><br>
                                    After starting a measurement, the sensor reading will settle after 10 seconds. For the most accurate measurement, a measurement time of approximately 15 seconds is proposed.
                                </div>
                                <h2>Interpreting the sensor reading</h2>
                                <div class="explanation">
                                    Particulate matter comes in a wide range of sizes, but the greatest impact on human health is typically associated with PM2.5 (which includes PM1). Because of their small size, PM2.5 particles can penetrate deeply into the human respiratory system and cause serious health effects.
                                    PM2.5 is also the most widely standardized and internationally recognized metric for assessing air quality. In contrast, PM1 and PM10 have some level of standardization, but their usage varies depending on countries, cities, industries, and specific application use-cases.
                                    <br><br>
                                    Air Quality Indices (AQIs) are used to communicate air pollution levels to the public. PM2.5 concentration is a key input for most AQIs. For example, the United States Environmental Protection Agency (EPA) uses PM2.5 to define its air quality thresholds.
                                    <br><br>
                                    <div class="explanationBoxWrapper">
                                        <div class="explanationGreen explanationCommon">
                                            Good: 0–12.0 µg/m³
                                            <ul>
                                                <li>Air quality is satisfactory, and air pollution poses little or no risk.</li>
                                            </ul>
                                        </div>
                                        <div class="explanationYellow explanationCommon">
                                            Moderate: 12.1–35.4 µg/m³
                                            <ul>
                                                <li>Air quality is acceptable. However, there may be a risk for some people, particularly those who are unusually sensitive to air pollution.</li>
                                            </ul>
                                        </div>
                                        <div class="explanationOrange explanationCommon">
                                            Unhealthy for sensitive groups : 35.5–55.4 µg/m³
                                            <ul>
                                                <li>Members of sensitive groups may experience health effects.
                                                The general public is less likely to be affected.</li>
                                            </ul>
                                        </div>
                                        <div class="explanationRed explanationCommon">
                                            Unhealthy : 55.5–150.4 µg/m³
                                            <ul>
                                                <li>Some members of the general public may experience health effects;
                                                members of sensitive groups may experience more serious health effects.</li>
                                            </ul>
                                        </div>
                                        <div class="explanationPurple explanationCommon">
                                            Very unhealthy: 150.5–250.4 µg/m³
                                            <ul>
                                                <li>Health alert: the risk of health effects is increased for everyone.</li>
                                            </ul>
                                        </div>
                                        <div class="explanationBrown explanationCommon">
                                        Hazardous: > 250.4 µg/m³
                                        <ul>
                                            <li>Health warnings of emergency conditions: everyone more likely to be affected.</li>
                                        </ul>
                                        </div>
                                    </div>
                                </div>
                            </div>`;

var settingsContentElementID = document.getElementById("settingsContent");

var helpContentElementID = document.getElementById("helpContent");
if(helpContentElementID != null) {
    helpContentElementID.parentNode.removeChild(helpContentElementID);
}

var gaugeRanges_EU = [{
 color : "#008000", //green
 lo : convertToLogScale(0),
 hi : convertToLogScale(12)
},{
 color : "#FFFF00", // yellow
 lo : convertToLogScale(13),
 hi : convertToLogScale(35)
},{
 color : "#FFC90e", // orange
 lo : convertToLogScale(36),
 hi : convertToLogScale(55)
},{
 color : "#ff0000", //red
 lo : convertToLogScale(56),
 hi : convertToLogScale(150)
},{
 color : "#9400D3", //purple
 lo : convertToLogScale(151),
 hi : convertToLogScale(250)
},{
 color : "#7e0023", //brownish
 lo : convertToLogScale(251),
 hi : convertToLogScale(1000)
}];

settingsContentElementID.insertAdjacentHTML("afterend", helpContentEUHtml);
gaugePM25.config.customSectors.ranges = gaugeRanges_EU;
gaugePM10.config.customSectors.ranges = gaugeRanges_EU;
gaugePM1.config.customSectors.ranges = gaugeRanges_EU;