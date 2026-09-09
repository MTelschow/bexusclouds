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

function loadLicenses()
{
    $("#headline").text("About");
    $(".tab").css("display","none");
    $("#userContent").css("display","block");
    $("#userContent").html(licensesHTML)
    document.getElementById("mainmenu").classList.remove("mdc-drawer--open");
}

const licensesHTML = `
<table>
    <tr>
        <td width="5%"></td>
        <td>
            <p class="mdc-typography--subtitle2"> BMV080 Web App</p>
            <p class="mdc-typography--body4"> Copyright (c) 2025 Bosch Sensortec GmbH</p>
            <p class="mdc-typography--body4"> End User License Agreement:</p>
            <p class="mdc-typography--body4"> Bosch Sensortec products are developed for the consumer goods industry. They may only be used within the parameters of the respective valid product data sheet. Bosch Sensortec products are provided with the express understanding that there is no warranty of fitness for a particular purpose. They are not fit for use in life-sustaining, safety or security sensitive systems or any system or device that may lead to bodily harm or property damage if the system or device malfunctions. In addition, Bosch Sensortec products are not fit for use in products which interact with motor vehicle systems. The resale and/or use of products are at the purchasers own risk and his own responsibility. The examination of fitness for the intended use is the sole responsibility of the Purchaser.</p>
            <p class="mdc-typography--body4"> The purchaser shall indemnify Bosch Sensortec from all third party claims, including any claims for incidental, or consequential damages, arising from any product use not covered by the parameters of the respective valid product data sheet or not approved by Bosch Sensortec and reimburse Bosch Sensortec for all costs in connection with such claims.</p>
            <p class="mdc-typography--body4"> The purchaser must monitor the market for the purchased products, particularly with regard to product safety and inform Bosch Sensortec without delay of all security relevant incidents.</p>
            <p class="mdc-typography--body4"> Engineering Samples are marked with an asterisk (*) or (e). Samples may vary from the valid technical specifications of the product series. They are therefore not intended or fit for resale to third parties or for use in end products. Their sole purpose is internal client testing. The testing of an engineering sample may in no way replace the testing of a product series. Bosch Sensortec assumes no liability for the use of engineering samples. By accepting the engineering samples, the</p>
            <p class="mdc-typography--body4"> Purchaser agrees to indemnify Bosch Sensortec from all claims arising from the use of engineering samples.</p>
            <p class="mdc-typography--body4"> Special:</p>
            <p class="mdc-typography--body4"> This software module (hereinafter called "Software") and any information on application-sheets (hereinafter called "Information") is provided free of charge for the sole purpose to support your application work. The Software and Information is subject to the following terms and conditions:</p>
            <p class="mdc-typography--body4"> The Software is specifically designed for the exclusive use for Bosch Sensortec products by personnel who have special experience and training. Do not use this Software if you do not have the proper experience or training.</p>
            <p class="mdc-typography--body4"> This Software package is provided "as is" and without any expressed or implied warranties, including without limitation, the implied warranties of merchantability and fitness for a particular purpose.</p>
            <p class="mdc-typography--body4"> Bosch Sensortec and their representatives and agents deny any liability for the functional impairment of this Software in terms of fitness, performance and safety. Bosch Sensortec and their representatives and agents shall not be liable for any direct or indirect damages or injury, except as otherwise stipulated in mandatory applicable law.</p>
            <p class="mdc-typography--body4"> The Information provided is believed to be accurate and reliable. Bosch Sensortec assumes no responsibility for the consequences of use of such Information nor for any infringement of patents or other rights of third parties which may result from its use. No license is granted by implication or otherwise under any patent or patent rights of Bosch. Specifications mentioned in the Information are subject to change without notice.</p>
            <p class="mdc-typography--body4"> It is neither permitted to deliver the source code of the Software to any third party without permission of Bosch Sensortec, nor to apply any measures to re-engineer or reverse-analyze the software delivered.</p>
            <br></br>
            <hr class="mdc-list-divider">
        
            <p class="mdc-typography--body4"> BMV080 Web App by Bosch Sensortec GmbH uses the following components with their respective licenses: </p>

            <p class="mdc-typography--subtitle2"> Bosch Sensortec COINES SDK </p>
            <p class="mdc-typography--body3"> 2.10.4 </p>
            <p class="mdc-typography--body4"> Copyright (c) 2024 Bosch Sensortec GmbH. All rights reserved. </p>
            <p class="mdc-typography--body4"> Bosch Sensortec COINES SDK is licensed under the <a href="https://github.com/boschsensortec/COINES_SDK/blob/main/COINES_SDK_SoftwareLicenseAgreement.txt">COINES SDK Software License Agreement</a>. </p>
            <hr class="mdc-list-divider">

            <p class="mdc-typography--subtitle2"> JQuery </p>
            <p class="mdc-typography--body3"> 3.4.1 </p>
            <p class="mdc-typography--body4"> Copyright (c) 2005, 2014 jQuery Foundation, Inc. </p>
            <p class="mdc-typography--body4"> JQuery is licensed under the <a href="#MIT">MIT License (MIT)</a>. </p>
            <hr class="mdc-list-divider">

            <p class="mdc-typography--subtitle2"> Material Components Web </p>
            <p class="mdc-typography--body3"> 14.0.0 </p>
            <p class="mdc-typography--body4"> Copyright (c) 2014-2020 Google Inc. </p>
            <p class="mdc-typography--body4"> Material Components Web is licensed under the <a href="#MIT">MIT License (MIT)</a>. </p>
            <hr class="mdc-list-divider">

            <p class="mdc-typography--subtitle2"> Material Design Icons </p>
            <p class="mdc-typography--body3"> 4.0.0 </p>
            <p class="mdc-typography--body4"> Copyright (c) 2020 Google Inc. </p>
            <p class="mdc-typography--body4"> Material Design Icons is licensed under the <a href="#Apache">Apache License 2.0</a>. </p>
            <hr class="mdc-list-divider">

            <p class="mdc-typography--subtitle2"> Normalize </p>
            <p class="mdc-typography--body3"> 7.0.0 </p>
            <p class="mdc-typography--body4"> Copyright (c) 2016 Nicolas Gallagher and Jonathan Neal </p>
            <p class="mdc-typography--body4"> Normalize is licensed under the <a href="#MIT">MIT License (MIT)</a>. </p>
            <hr class="mdc-list-divider">

            <p class="mdc-typography--subtitle2"> Plotly </p>
            <p class="mdc-typography--body3"> 3.0.1 </p>
            <p class="mdc-typography--body4"> Copyright (c) 2025 Plotly, Inc. </p>
            <p class="mdc-typography--body4"> Plotly is licensed under the <a href="#MIT">MIT License (MIT)</a>. </p>
            <hr class="mdc-list-divider">

            <p class="mdc-typography--subtitle2"> Just Gage </p>
            <p class="mdc-typography--body3"> 1.2.2 </p>
            <p class="mdc-typography--body4"> Copyright (c) 2012-2015 Bojan Djuricic </p>
            <p class="mdc-typography--body4"> Just Gage is licensed under the <a href="#MIT">MIT License (MIT)</a>. </p>
            <hr class="mdc-list-divider">

            <p class="mdc-typography--subtitle2"> Raphael Vector Library </p>
            <p class="mdc-typography--body3"> 2.1.4 </p>
            <p class="mdc-typography--body4"> Copyright (c) 2008-2012 Dmitry Baranovskiy (<a href="http://raphaeljs.com">http://raphaeljs.com</a>)</p>
            <p class="mdc-typography--body4"> Copyright (c) 2008-2012 Sencha Labs (<a href="http://sencha.com">http://sencha.com</a>) </p>
            <p class="mdc-typography--body4"> Raphael Vector Library is licensed under the <a href="#MIT">MIT License (MIT)</a>. </p>
            <hr class="mdc-list-divider">

            <p class="mdc-typography--subtitle2"> Loaders </p>
            <p class="mdc-typography--body3"> 0.1.2 </p>
            <p class="mdc-typography--body4"> Copyright (c) 2016 Connor Atherton (<a href="https://github.com/ConnorAtherton/loaders.css/releases/tag/0.1.2">https://github.com/ConnorAtherton/loaders.css/releases/tag/0.1.2</a>) </p>
            <p class="mdc-typography--body4"> Loaders is licensed under the <a href="#MIT">MIT License (MIT)</a>. </p>
            </p>
            <hr id = "lastComponent" class="mdc-list-divider">

            <p class="mdc-typography--subtitle2" id="Apache"> Apache License 2.0 </p>
            <p class="mdc-typography--body4"> This license applies to various files in the codebase. </p>
            <p class="mdc-typography--body4"> Apache License </p>
            <p class="mdc-typography--body4"> Version 2.0, January 2004 </p>
            <p class="mdc-typography--body4"> <a href="http://www.apache.org/licenses/">http://www.apache.org/licenses/</a></p>
            <p class="mdc-typography--body4"> TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION </p>
            <p class="mdc-typography--body4"> 1. Definitions. </p>
            <p class="mdc-typography--body4"> "License" shall mean the terms and conditions for use, reproduction, and distribution as defined by Sections 1 through 9 of this document.</p>
            <p class="mdc-typography--body4"> "Licensor" shall mean the copyright owner or entity authorized by the copyright owner that is granting the License. </p>
            <p class="mdc-typography--body4"> "Legal Entity" shall mean the union of the acting entity and all other entities that control, are controlled by, or are under common control with that entity. For the purposes of this definition, "control" means (i) the
                power, direct or indirect, to cause the direction or management of such entity, whether by contract or otherwise, or (ii) ownership of fifty percent (50%) or more of the outstanding shares, or (iii) beneficial ownership
                of such entity.</p>
            <p class="mdc-typography--body4"> "You" (or "Your") shall mean an individual or Legal Entity exercising permissions granted by this License. </p>
            <p class="mdc-typography--body4"> "Source" form shall mean the preferred form for making modifications, including but not limited to software source code, documentation source, and configuration files.</p>
            <p class="mdc-typography--body4"> "Object" form shall mean any form resulting from mechanical transformation or translation of a Source form, including but not limited to compiled object code, generated documentation, and conversions to other media types.
            </p>
            <p class="mdc-typography--body4"> "Work" shall mean the work of authorship, whether in Source or Object form, made available under the License, as indicated by a copyright notice that is included in or attached to the work (an example is provided in the
                Appendix below). </p>
            <p class="mdc-typography--body4"> "Derivative Works" shall mean any work, whether in Source or Object form, that is based on (or derived from) the Work and for which the editorial revisions, annotations, elaborations, or other modifications represent, as
                a whole, an original work of authorship. For the purposes of this License, Derivative Works shall not include works that remain separable from, or merely link (or bind by name) to the interfaces of, the Work and Derivative
                Works thereof.</p>
            <p class="mdc-typography--body4"> "Contribution" shall mean any work of authorship, including the original version of the Work and any modifications or additions to that Work or Derivative Works thereof, that is intentionally submitted to Licensor for inclusion
                in the Work by the copyright owner or by an individual or Legal Entity authorized to submit on behalf of the copyright owner. For the purposes of this definition, "submitted" means any form of electronic, verbal, or
                written communication sent to the Licensor or its representatives, including but not limited to communication on electronic mailing lists, source code control systems, and issue tracking systems that are managed by,
                or on behalf of, the Licensor for the purpose of discussing and improving the Work, but excluding communication that is conspicuously marked or otherwise designated in writing by the copyright owner as "Not a Contribution."
            </p>
            <p class="mdc-typography--body4"> "Contributor" shall mean Licensor and any individual or Legal Entity on behalf of whom a Contribution has been received by Licensor and subsequently incorporated within the Work. </p>
            <p class="mdc-typography--body4"> 2. Grant of Copyright License. Subject to the terms and conditions of this License, each Contributor hereby grants to You a perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable copyright license to
                reproduce, prepare Derivative Works of, publicly display, publicly perform, sublicense, and distribute the Work and such Derivative Works in Source or Object form.</p>
            <p class="mdc-typography--body4"> 3. Grant of Patent License. Subject to the terms and conditions of this License, each Contributor hereby grants to You a perpetual, worldwide, non-exclusive, no-charge, royalty-free, irrevocable (except as stated in this
                section) patent license to make, have made, use, offer to sell, sell, import, and otherwise transfer the Work, where such license applies only to those patent claims licensable by such Contributor that are necessarily
                infringed by their Contribution(s) alone or by combination of their Contribution(s) with the Work to which such Contribution(s) was submitted. If You institute patent litigation against any entity (including a cross-claim
                or counterclaim in a lawsuit) alleging that the Work or a Contribution incorporated within the Work constitutes direct or contributory patent infringement, then any patent licenses granted to You under this License
                for that Work shall terminate as of the date such litigation is filed.</p>
            <p class="mdc-typography--body4"> 4. Redistribution. You may reproduce and distribute copies of the Work or Derivative Works thereof in any medium, with or without modifications, and in Source or Object form, provided that You meet the following conditions:</p>
            <p class="mdc-typography--body4"> (a) You must give any other recipients of the Work or Derivative Works a copy of this License; and</p>
            <p class="mdc-typography--body4"> (b) You must cause any modified files to carry prominent notices stating that You changed the files; and</p>
            <p class="mdc-typography--body4"> (c) You must retain, in the Source form of any Derivative Works that You distribute, all copyright, patent, trademark, and attribution notices from the Source form of the Work, excluding those notices that do not pertain
                to any part of the Derivative Works; and </p>
            <p class="mdc-typography--body4"> (d) If the Work includes a "NOTICE" text file as part of its distribution, then any Derivative Works that You distribute must include a readable copy of the attribution notices contained within such NOTICE file, excluding
                those notices that do not pertain to any part of the Derivative Works, in at least one of the following places: within a NOTICE text file distributed as part of the Derivative Works; within the Source form or documentation,
                if provided along with the Derivative Works; or, within a display generated by the Derivative Works, if and wherever such third-party notices normally appear. The contents of the NOTICE file are for informational purposes
                only and do not modify the License. You may add Your own attribution notices within Derivative Works that You distribute, alongside or as an addendum to the NOTICE text from the Work, provided that such additional attribution
                notices cannot be construed as modifying the License.</p>
            <p class="mdc-typography--body4"> You may add Your own copyright statement to Your modifications and may provide additional or different license terms and conditions for use, reproduction, or distribution of Your modifications, or for any such Derivative
                Works as a whole, provided Your use, reproduction, and distribution of the Work otherwise complies with the conditions stated in this License.</p>
            <p class="mdc-typography--body4"> 5. Submission of Contributions. Unless You explicitly state otherwise, any Contribution intentionally submitted for inclusion in the Work by You to the Licensor shall be under the terms and conditions of this License, without
                any additional terms or conditions. Notwithstanding the above, nothing herein shall supersede or modify the terms of any separate license agreement you may have executed with Licensor regarding such Contributions.</p>
            <p class="mdc-typography--body4"> 6. Trademarks. This License does not grant permission to use the trade names, trademarks, service marks, or product names of the Licensor, except as required for reasonable and customary use in describing the origin of
                the Work and reproducing the content of the NOTICE file.</p>
            <p class="mdc-typography--body4"> 7. Disclaimer of Warranty. Unless required by applicable law or agreed to in writing, Licensor provides the Work (and each Contributor provides its Contributions) on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
                ANY KIND, either express or implied, including, without limitation, any warranties or conditions of TITLE, NON-INFRINGEMENT, MERCHANTABILITY, or FITNESS FOR A PARTICULAR PURPOSE. You are solely responsible for determining
                the appropriateness of using or redistributing the Work and assume any risks associated with Your exercise of permissions under this License. </p>
            <p class="mdc-typography--body4"> 8. Limitation of Liability. In no event and under no legal theory, whether in tort (including negligence), contract, or otherwise, unless required by applicable law (such as deliberate and grossly negligent acts) or agreed
                to in writing, shall any Contributor be liable to You for damages, including any direct, indirect, special, incidental, or consequential damages of any character arising as a result of this License or out of the use
                or inability to use the Work (including but not limited to damages for loss of goodwill, work stoppage, computer failure or malfunction, or any and all other commercial damages or losses), even if such Contributor has
                been advised of the possibility of such damages. </p>
            <p class="mdc-typography--body4"> 9. Accepting Warranty or Additional Liability. While redistributing the Work or Derivative Works thereof, You may choose to offer, and charge a fee for, acceptance of support, warranty, indemnity, or other liability obligations
                and/or rights consistent with this License. However, in accepting such obligations, You may act only on Your own behalf and on Your sole responsibility, not on behalf of any other Contributor, and only if You agree
                to indemnify, defend, and hold each Contributor harmless for any liability incurred by, or claims asserted against, such Contributor by reason of your accepting any such warranty or additional liability. </p>
            <p class="mdc-typography--body4"> END OF TERMS AND CONDITIONS </p>
            <hr class="mdc-list-divider">

            <p class="mdc-typography--subtitle2" id="BSD-3"> BSD 3-Clause "New" or "Revised" License </p>
            <p class="mdc-typography--body4"> Redistribution and use in source and binary forms, with or without modification,
                                              are permitted provided that the following conditions are met:
            <p class="mdc-typography--body4"> 1. Redistributions of source code must retain the above copyright notice,
                                                 this list of conditions and the following disclaimer. </p>
            <p class="mdc-typography--body4"> 2. Redistributions in binary form must reproduce the above copyright notice,
                                                 this list of conditions and the following disclaimer in the documentation
                                                 and/or other materials provided with the distribution. </p>
            <p class="mdc-typography--body4"> 3. Neither the name of the copyright holder nor the names of its
                                                 contributors may be used to endorse or promote products derived from
                                                 this software without specific prior written permission. </p>
            <p class="mdc-typography--body4"> THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
                                              AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
                                              IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
                                              DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
                                              FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
                                              DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
                                              SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
                                              CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
                                              OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
                                              OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE. </p>
            <hr class="mdc-list-divider">

            <p class="mdc-typography--subtitle2" id="MIT"> MIT Licence </p>
            <p class="mdc-typography--body4"> This license applies to various files in the codebase. </p>
            <p class="mdc-typography--body4"> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation
                the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions: </p>
            <p class="mdc-typography--body4"> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software. </p>
            <p id = "lastParagraph" class="mdc-typography--body4"> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
                THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
                DEALINGS IN THE SOFTWARE. </p>
        </td>
        <td width="5%"></td>
    </tr>
</table>`