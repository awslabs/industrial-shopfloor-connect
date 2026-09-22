// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0
//

package com.amazonaws.sfc.opcuatarget

import org.eclipse.milo.opcua.sdk.server.identity.UsernameIdentityValidator

// milo 1.1.7 dropped the allowAnonymousAccess constructor flag - anonymous access is now
// provided by composing in AnonymousIdentityValidator (see OpcuaTargetServer).
class UserNameValidator : UsernameIdentityValidator({ false })
