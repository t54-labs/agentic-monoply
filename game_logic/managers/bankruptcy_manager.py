from typing import Optional
from .base_manager import BaseManager
from ..player import Player


class BankruptcyManager(BaseManager):
    """
    Handles bankruptcy mechanics including asset liquidation,
    debt settlement, and player elimination.
    """
    
    def get_manager_name(self) -> str:
        return "BankruptcyManager"
    
    def check_and_handle_bankruptcy(self, player: Player, debt_to_creditor: int = 0, creditor: Optional[Player] = None) -> None:
        """
        Check if a player should be declared bankrupt and handle the process.
        
        Args:
            player: The player to check for bankruptcy
            debt_to_creditor: Amount owed that triggered bankruptcy check
            creditor: The player or entity owed money (None for system debt)
        """
        if player.is_bankrupt:
            self.log_event(f"{player.name} is already bankrupt", "bankruptcy_event")
            return
            
        # Check if player can potentially pay the debt
        total_assets = self._calculate_total_asset_value(player)
        
        if total_assets < debt_to_creditor:
            self.log_event(f"{player.name} cannot cover ${debt_to_creditor} debt even with all assets (${total_assets})", "bankruptcy_event")
            self._finalize_bankruptcy_declaration(player, creditor)
        elif player.money < debt_to_creditor:
            # Player doesn't have cash but might have assets to liquidate
            self.log_event(f"{player.name} needs to liquidate assets to pay ${debt_to_creditor} debt", "bankruptcy_event")
            self._initiate_asset_liquidation(player, debt_to_creditor, creditor)
        else:
            # Player has sufficient cash - shouldn't be bankrupt
            self.log_event(f"{player.name} has sufficient cash (${player.money}) for ${debt_to_creditor} debt", "bankruptcy_event")
    
    def _calculate_total_asset_value(self, player: Player) -> int:
        """
        Calculate the total liquidation value of a player's assets.
        
        Args:
            player: The player whose assets to calculate
            
        Returns:
            int: Total liquidation value of all assets
        """
        total_value = player.money
        
        for prop_id in player.properties_owned_ids:
            property_square = self.board.get_square(prop_id)
            
            # Add mortgage value for unmortgaged properties
            if hasattr(property_square, 'is_mortgaged') and not property_square.is_mortgaged:
                total_value += property_square.price // 2  # Mortgage value is 50% of price
                
            # Add house sale value if applicable
            if hasattr(property_square, 'num_houses') and property_square.num_houses > 0:
                # Houses sell for 50% of purchase price
                if property_square.num_houses == 5:  # Hotel (represented as 5 houses)
                    house_value = 4 * (property_square.house_price // 2)  # 4 houses worth + hotel conversion
                else:
                    house_value = property_square.num_houses * (property_square.house_price // 2)
                total_value += house_value
                
        return total_value
    
    def _initiate_asset_liquidation(self, player: Player, debt_amount: int, creditor: Optional[Player]) -> None:
        """
        Initiate the asset liquidation process for a player.
        
        Args:
            player: The player who needs to liquidate assets
            debt_amount: Amount of debt to be paid
            creditor: The creditor (player or None for system)
        """
        self.log_event(f"{player.name} must liquidate assets to pay ${debt_amount} debt", "bankruptcy_event")
        
        # Set pending decision for asset liquidation
        self.gc._set_pending_decision(
            "asset_liquidation_for_debt",
            context={
                "player_id": player.player_id,
                "debt_amount": debt_amount,
                "creditor_id": creditor.player_id if creditor else None,
                "creditor_name": creditor.name if creditor else "Bank",
                "total_asset_value": self._calculate_total_asset_value(player)
            },
            outcome_processed=False
        )
    
    def confirm_asset_liquidation_done(self, player_id: int) -> None:
        """
        Confirm that a player has finished liquidating assets.
        
        Args:
            player_id: ID of the player who finished liquidation
        """
        if not (0 <= player_id < len(self.players)):
            self.log_event(f"Invalid player_id for asset liquidation: {player_id}", "error_bankruptcy")
            return
            
        player = self.players[player_id]
        context = self.gc.pending_decision_context
        
        debt_amount = context.get("debt_amount", 0)
        creditor_id = context.get("creditor_id")
        creditor = self.players[creditor_id] if creditor_id is not None else None
        
        if player.money >= debt_amount:
            self.log_event(f"{player.name} successfully liquidated enough assets to pay ${debt_amount} debt", "bankruptcy_event")
            
            # Execute the actual debt payment
            import asyncio
            try:
                if creditor:
                    # Pay to another player
                    payment_success = asyncio.run(
                        self.gc.payment_manager.create_tpay_payment_player_to_player(
                            payer=player,
                            recipient=creditor,
                            amount=float(debt_amount),
                            reason=f"debt payment after asset liquidation",
                            agent_decision_context={
                                "bankruptcy_context": "asset_liquidation_debt_payment",
                                "original_debt": debt_amount,
                                "liquidated_assets": True
                            }
                        )
                    )
                else:
                    # Pay to system/bank
                    payment_success = asyncio.run(
                        self.gc.payment_manager.create_tpay_payment_player_to_system(
                            payer=player,
                            amount=float(debt_amount),
                            reason=f"debt payment after asset liquidation",
                            agent_decision_context={
                                "bankruptcy_context": "asset_liquidation_debt_payment",
                                "original_debt": debt_amount,
                                "liquidated_assets": True
                            }
                        )
                    )
                
                if payment_success:
                    self.log_event(f"✅ {player.name} successfully paid ${debt_amount} debt after asset liquidation", "bankruptcy_event")
                    self.gc._resolve_current_action_segment()
                else:
                    self.log_event(f"❌ {player.name} debt payment failed after asset liquidation - proceeding to bankruptcy", "bankruptcy_event")
                    self._finalize_bankruptcy_declaration(player, creditor)
            except Exception as e:
                self.log_event(f"❌ Error executing debt payment for {player.name}: {e} - proceeding to bankruptcy", "error_bankruptcy")
                self._finalize_bankruptcy_declaration(player, creditor)
        else:
            self.log_event(f"{player.name} still cannot pay ${debt_amount} debt after liquidation (has ${player.money})", "bankruptcy_event")
            self._finalize_bankruptcy_declaration(player, creditor)
    
    def _finalize_bankruptcy_declaration(self, player: Player, creditor: Optional[Player]) -> None:
        """
        Finalize the bankruptcy declaration and transfer assets.
        
        Args:
            player: The player being declared bankrupt
            creditor: The creditor receiving assets (None for system)
        """
        if player.is_bankrupt:
            return  # Already bankrupt
            
        self.log_event(f"{player.name} is declared BANKRUPT!", "bankruptcy_event")
        player.is_bankrupt = True
        
        # Transfer all properties
        properties_transferred = []
        for prop_id in player.properties_owned_ids.copy():
            property_square = self.board.get_square(prop_id)
            
            if creditor:
                # Transfer to creditor player
                property_square.owner_id = creditor.player_id
                creditor.add_property_id(prop_id)
                properties_transferred.append(f"{property_square.name} -> {creditor.name}")
                
                # Handle mortgaged properties
                if hasattr(property_square, 'is_mortgaged') and property_square.is_mortgaged:
                    creditor.pending_mortgaged_properties_to_handle.append({
                        "property_id": prop_id,
                        "property_name": property_square.name,
                        "mortgage_value": property_square.price // 2
                    })
            else:
                # Return to bank (no owner)
                property_square.owner_id = None
                # Remove any houses/hotels
                if hasattr(property_square, 'num_houses'):
                    property_square.num_houses = 0
                # Unmortgage properties returned to bank
                if hasattr(property_square, 'is_mortgaged'):
                    property_square.is_mortgaged = False
                properties_transferred.append(f"{property_square.name} -> Bank")
            
            player.remove_property_id(prop_id)
        
        if properties_transferred:
            self.log_event(f"Properties transferred: {', '.join(properties_transferred)}", "bankruptcy_event")
        
        # Transfer any remaining money to creditor
        if player.money > 0 and creditor:
            # Execute TPay transfer of remaining money
            import asyncio
            try:
                remaining_money = player.money
                payment_success = asyncio.run(
                    self.gc.payment_manager.create_tpay_payment_player_to_player(
                        payer=player,
                        recipient=creditor,
                        amount=float(remaining_money),
                        reason=f"bankruptcy asset transfer",
                        agent_decision_context={
                            "bankruptcy_context": "final_asset_transfer",
                            "transfer_type": "remaining_money"
                        }
                    )
                )
                
                if payment_success:
                    self.log_event(f"✅ ${remaining_money} transferred from {player.name} to {creditor.name}", "bankruptcy_event")
                else:
                    self.log_event(f"❌ Failed to transfer ${remaining_money} from {player.name} to {creditor.name}", "error_bankruptcy")
                    # Even if transfer fails, still clear player money as they're bankrupt
                    player.money = 0
            except Exception as e:
                self.log_event(f"❌ Error transferring money from {player.name} to {creditor.name}: {e}", "error_bankruptcy")
                player.money = 0
        else:
            # Clear player money (either no creditor or no money to transfer)
            player.money = 0
        
        # Clear player state
        player.money = 0
        player.position = 0  # Move to GO or jail
        
        self.log_event(f"{player.name} bankruptcy finalized", "bankruptcy_event")
        
        # Check if game should end
        self.gc._check_for_game_over_condition()
        self.gc._resolve_current_action_segment()
    
    def finalize_bankruptcy_declaration(self, player: Player, creditor: Optional[Player]) -> None:
        """
        Public method to finalize bankruptcy (for external calls).
        
        Args:
            player: The player being declared bankrupt
            creditor: The creditor receiving assets
        """
        self._finalize_bankruptcy_declaration(player, creditor) 